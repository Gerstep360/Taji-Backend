import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from auditlog.services import record_audit_event
from community.api import allowed
from security.models import VisualObservation as Observation, VisualQuota, VisualSession
from tenancy.context import TenantContext
from tenancy.models import TenantMembership

from .visual_provider import COSMOS, HOSTED, OMNI, ProviderError, request_visual
from .visual_reasoning import PROMPT, STATIC, contextual_matches, normalize, terms

log = logging.getLogger(__name__)
STATE = Observation.Status
IN_FLIGHT = (STATE.QUEUED, STATE.RUNNING)
SESSION_DURATION = timedelta(minutes=20)
QUEUE_DURATION = timedelta(seconds=55)
WORKER_GRACE = timedelta(seconds=75)


def provider_for(mode):
    config = settings.TAJI_VISION
    if config['COSMOS_KEY'] and (config['COSMOS_MODE'] == mode or config['COSMOS_MODE'] == 'video'):
        return config['COSMOS_URL'], config['COSMOS_KEY'], COSMOS
    if config['FALLBACK_KEY'] and config['FALLBACK_VERIFIED' if mode == 'image' else 'FALLBACK_VIDEO_VERIFIED']:
        return HOSTED, config['FALLBACK_KEY'], OMNI
    return None


def close_session(session, now):
    if session.ended_at is None:
        session.ended_at = now
        session.save(update_fields=['ended_at'])
    session.observations.filter(status__in=IN_FLIGHT).update(status=STATE.CANCELLED, payload=None)


def expire(now):
    sessions = VisualSession.objects.filter(ended_at__isnull=True, expires_at__lte=now)
    for pk in sessions.values_list('pk', flat=True).iterator():
        with transaction.atomic():
            session = VisualSession.objects.select_for_update().filter(pk=pk, expires_at__lte=now).first()
            if session:
                close_session(session, now)
    Observation.objects.filter(status=STATE.QUEUED, received_at__lte=now - QUEUE_DURATION).update(
        status=STATE.FAILED, payload=None, provider_error='queue_expired')
    Observation.objects.filter(status=STATE.RUNNING, started_at__lte=now - timedelta(seconds=150)).update(
        status=STATE.FAILED, payload=None, provider_error='worker_interrupted')


def purge(now):
    before = now - timedelta(days=settings.TAJI_VISION['RETENTION_DAYS'])
    Observation.objects.filter(observed_until__lt=before).delete()
    VisualSession.objects.filter(ended_at__lt=before, observations__isnull=True).delete()


@transaction.atomic
def claim(now):
    quota, _ = VisualQuota.objects.select_for_update().get_or_create(pk=1)
    quota.worker_seen_at = now
    quota.save(update_fields=['worker_seen_at'])
    job = Observation.objects.filter(status=STATE.QUEUED, session__ended_at__isnull=True,
                                     session__expires_at__gt=now, received_at__gt=now - QUEUE_DURATION).order_by('received_at').first()
    if job is None:
        return None
    payload = bytes(job.payload or b'')
    updated = Observation.objects.filter(pk=job.pk, status=STATE.QUEUED).update(
        status=STATE.RUNNING, started_at=now, payload=None)
    return (job.pk, payload) if updated else None


def recent_memory(session):
    # Bounded confirmed/rejected examples, summarized as decisions, not sent to NVIDIA.
    return list(Observation.objects.filter(session__condominium_id=session.condominium_id,
        session__sector_id=session.sector_id, reviewed_at__isnull=False)
        .order_by('-reviewed_at').values_list('prediction', 'review_status')[:20])


def duplicate(job, prediction):
    words = terms(prediction['description'] + ' ' + ' '.join(prediction['visible_entities']))
    recent = Observation.objects.filter(session=job.session, status=STATE.SUCCEEDED,
        observed_until__gte=job.observed_until - timedelta(minutes=3)).exclude(pk=job.pk).order_by('-observed_until')[:8]
    for item in recent.defer('payload', 'evidence'):
        if item.prediction.get('suggested_action') != prediction['suggested_action']:
            continue
        previous = terms(item.description + ' ' + ' '.join(item.prediction.get('visible_entities', [])))
        if item.description.casefold() == prediction['description'].casefold() or (
                len(words & previous) >= 2 and len(words & previous) / len(words | previous) >= .8):
            return True
    return False


def process(job_id, payload):
    job = Observation.objects.select_related('session__condominium', 'session__owner').defer('payload', 'evidence').get(pk=job_id)
    session = job.session
    if job.status != STATE.RUNNING:
        return
    user, tenant = session.owner, session.condominium
    member = TenantMembership.objects.filter(condominium=tenant, user=user, is_active=True).select_related('role').first()
    with TenantContext.for_tenant(tenant, member):
        prediction, matches, model, ms, error = {}, [], '', None, ''
        try:
            if not (tenant.is_active and user.is_active and user.is_approved and allowed(user, 'validate_visits')):
                raise ProviderError('access_revoked')
            if not payload or session.ended_at or session.expires_at <= timezone.now():
                raise ProviderError('session_closed')
            provider = provider_for(job.mode) if settings.TAJI_VISION['ENABLED'] else None
            if provider is None:
                raise ProviderError('provider_unavailable')
            prompt = PROMPT + ('\n' + STATIC if job.mode == 'image' else '')
            raw, model, ms = request_visual(*provider, payload, job.mode, prompt, settings.TAJI_VISION['TIMEOUT'], structured=True)
            prediction = normalize(raw, job.mode)
            if prediction['suggested_action'] != 'ignore':
                matches = contextual_matches(session, prediction)
                signature = terms(' '.join(prediction['visible_entities']))
                for previous, decision in recent_memory(session):
                    if signature and signature == terms(' '.join(previous.get('visible_entities', []))):
                        prediction['prior_review'] = decision  # contextual signal, never auto-confirms/dismisses
                        break
        except ProviderError as exc:
            error = exc.code
        except (TypeError, ValueError, RecursionError):
            error = 'invalid_response'
        except Exception:
            log.error('CU32 visual job %s failed unexpectedly', job_id)
            error = 'processing_error'

        with transaction.atomic():
            session = VisualSession.objects.select_for_update().get(pk=session.pk)
            job = Observation.objects.select_for_update().defer('payload', 'evidence').get(pk=job.pk)
            if job.status != STATE.RUNNING:
                return
            job.model_id, job.provider_ms, job.provider_error = model, ms, error
            if session.ended_at or session.expires_at <= timezone.now():
                job.status = STATE.CANCELLED
            elif error:
                job.status = STATE.FAILED
            elif prediction['suggested_action'] == 'ignore' or duplicate(job, prediction):
                job.status = STATE.SKIPPED
            else:
                job.status = STATE.SUCCEEDED
                job.description = prediction['description']
                job.prediction = prediction
                job.matches = matches
                if session.keep_evidence:
                    job.evidence = payload
                    job.has_evidence = True
            job.save()
            if job.status == STATE.SUCCEEDED:
                record_audit_event(action_code='visual_observation.created', resource_type='visual_observation',
                                   resource_id=job.pk, actor_user=user, after_data={'related_codes': [m['code'] for m in matches]})
