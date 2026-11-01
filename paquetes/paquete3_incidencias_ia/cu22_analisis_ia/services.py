import hashlib
import json
from datetime import timedelta
from time import monotonic
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from auditlog.services import record_audit_event
from incidents.models import (Incident, IncidentAIAnalysis, IncidentAIEntity, IncidentAIReview,
                              IncidentCategory, PriorityLevel, RiskRule)
from .provider import analyze, ProviderFailure
from .serializers import PredictionSerializer
from .safety import evaluate, normalized, context_of
from .media import prepare_images

PROMPT_VERSION = 'cu22-4-threats'


def can_analyze(user):
    return bool(user and user.is_authenticated and (user.has_system_permission('manage_incidents') or user.has_system_permission('analyze_incidents')))


def can_review(user):
    return bool(user and user.is_authenticated and (user.has_system_permission('manage_incidents') or user.has_system_permission('review_incident_ai')))


def snapshot(incident):
    return {'title': incident.title[:160], 'description': incident.description[:6000],
            'location': incident.sector.name if incident.sector_id else '',
            'images': list(incident.attachments.filter(file_type='IMAGE').order_by('id').values('id', 'file_path')[:20])}


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@transaction.atomic
def enqueue(incident, user, *, automatic=False):
    if not automatic and not can_analyze(user):
        raise PermissionDenied('No tienes permiso para solicitar el análisis.')
    incident = Incident.objects.select_for_update(of=('self',)).select_related('sector').get(pk=incident.pk)
    active = incident.ai_analyses.filter(execution_status__in=('QUEUED', 'RUNNING')).first()
    if active:
        return active
    if not automatic and incident.ai_analyses.filter(created_at__gte=timezone.now() - timedelta(seconds=30)).exists():
        raise ValidationError('Espera 30 segundos antes de solicitar otro análisis.')
    data = snapshot(incident)
    result = IncidentAIAnalysis.objects.create(
        incident=incident, execution_status='QUEUED', requested_by=user,
        model_name=settings.NVIDIA['MODEL'][:100], model_version=PROMPT_VERSION,
        text_hash=fingerprint(data), input_snapshot=data,
    )
    record_audit_event(action_code='INCIDENT_AI_REQUEST', resource_type='IncidentAIAnalysis', resource_id=result.pk, actor_user=user)
    return result


@transaction.atomic
def claim_job():
    now = timezone.now()
    IncidentAIAnalysis.objects.filter(execution_status='RUNNING', started_at__lt=now - timedelta(minutes=2)).update(
        execution_status='FAILED', error_code='worker_interrupted', finished_at=now)
    job = IncidentAIAnalysis.objects.select_for_update(skip_locked=True).filter(execution_status='QUEUED').order_by('created_at', 'id').first()
    if job:
        updates = {'execution_status': 'RUNNING', 'started_at': now,
                   'model_name': settings.NVIDIA['MODEL'][:100], 'model_version': PROMPT_VERSION}
        # Compatibilidad con trabajos encolados antes del soporte multimodal.
        if 'images' not in job.input_snapshot:
            current = snapshot(job.incident)
            old = {key: current[key] for key in ('title', 'description', 'location')}
            if old == job.input_snapshot:
                updates.update(input_snapshot=current, text_hash=fingerprint(current))
        if not IncidentAIAnalysis.objects.filter(pk=job.pk, execution_status='QUEUED').update(**updates):
            return None
        job.refresh_from_db()
    return job


def process_job(job):
    started = monotonic()
    original = {}
    findings, floor, score = [], 0, 0
    rules = []
    try:
        text = job.input_snapshot['title'] + '\n' + job.input_snapshot['description']
        rules = list(RiskRule.objects.filter(is_active=True))
        findings, floor, score = evaluate(text, rules)
        categories = list(IncidentCategory.objects.filter(is_active=True).values('code', 'name', 'description'))
        priorities = list(PriorityLevel.objects.filter(is_active=True).values('code', 'name', 'rank'))
        images, media_manifest = prepare_images(job.input_snapshot.get('images', []),
            storage_prefix=f'incidents/{job.incident.condominium_id}/{job.incident_id}/')
        prediction, raw = analyze(job.input_snapshot, categories, priorities, images=images)
        original = {'prediction': prediction, 'provider_content': raw, 'media': media_manifest}
        validator = PredictionSerializer(data=prediction)
        if not validator.is_valid():
            raise ProviderFailure('invalid_response')
        data = validator.validated_data
        category = IncidentCategory.objects.filter(code=data['category_code'], is_active=True).first()
        priority = PriorityLevel.objects.filter(code=data['priority_code'], is_active=True).first()
        if not category or not priority:
            raise ProviderFailure('unknown_catalog_value')
        evidence_text = normalized(text + '\n' + job.input_snapshot.get('location', ''))
        if any(normalized(e['text']) not in evidence_text for e in data['entities']) or any(normalized(r['evidence']) not in evidence_text for r in data['risks'] if r['source'] == 'text'):
            raise ProviderFailure('ungrounded_evidence')
        sent_ids = {image['id'] for image in images}
        if any(r['attachment_id'] not in sent_ids for r in data['risks'] if r['source'] == 'image'):
            raise ProviderFailure('ungrounded_image')
        visual_text = '. '.join(r['name'] + ': ' + r['evidence'] for r in data['risks'] if r['source'] == 'image' and r['context'] == 'present')
        if visual_text:
            visual_findings, visual_floor, visual_score = evaluate(visual_text, rules)
            for finding in visual_findings:
                finding['source'] = 'image'
            findings.extend(visual_findings)
            floor = max(floor, visual_floor)
            score = max(score, visual_score)
        import re
        for risk in data['risks']:
            if risk['source'] == 'image':
                continue
            evidence = normalized(risk['evidence'])
            start = normalized(text).find(evidence)
            if start >= 0:
                verified_context = context_of(normalized(text), start, start + len(evidence),
                    allow_distant=bool(re.search(r'\b(ninos?|ninas?|personas?|vecinos?)\b', evidence)))
                if verified_context != 'present':
                    risk['context'] = verified_context
        if data['risks'] and all(risk['context'] in ('negated', 'distant', 'past', 'drill') for risk in data['risks']) and not floor:
            priority = PriorityLevel.objects.filter(is_active=True).order_by('rank').first()
            data['risk_score'] = 0
        safe_actions = []
        for action in data['recommendations']:
            forbidden = any(re.search(pattern, normalized(action)) for rule in rules
                for pattern in rule.conditions.get('forbidden_action_patterns', []))
            safe_actions.append('Mantén distancia del peligro y solicita atención al equipo competente.' if forbidden else action)
        data['recommendations'] = list(dict.fromkeys(safe_actions))
        if floor >= 3:
            active_codes = {f['rule'] for f in findings if f['active']}
            trusted_actions = [action for rule in rules if rule.code in active_codes for action in rule.conditions.get('safe_actions', [])]
            data['recommendations'] = list(dict.fromkeys(trusted_actions))[:8] or ['Mantén distancia del peligro y solicita atención al equipo competente.']
        if priority.rank < floor:
            priority = PriorityLevel.objects.filter(is_active=True, rank__gte=floor).order_by('rank').first()
            if not priority:
                raise ProviderFailure('missing_safety_priority')
        with transaction.atomic():
            current = IncidentAIAnalysis.objects.select_for_update().get(pk=job.pk)
            if current.execution_status != 'RUNNING':
                return current
            current.raw_output = original
            current.raw_output['validated_prediction'] = dict(data)
            current.suggested_category = category
            current.suggested_priority = priority
            current.suggested_staff_type = category.default_staff_type
            current.confidence = data['confidence']
            current.risk_score = max(score, data['risk_score'])
            current.safety_findings = findings
            current.suggested_action = '\n'.join(data['recommendations'])
            current.execution_status = 'SUCCEEDED'
            current.finished_at = timezone.now()
            current.duration_ms = int((monotonic() - started) * 1000)
            current.save()
            IncidentAIEntity.objects.bulk_create([
                IncidentAIEntity(analysis=current, entity_type=e['entity_type'].upper(), text_value=e['text'], normalized_value=e['context'])
                for e in data['entities']
            ])
            record_audit_event(action_code='INCIDENT_AI_ANALYZED', resource_type='IncidentAIAnalysis', resource_id=current.pk,
                               actor_user=current.requested_by, after_data={'priority': priority.code, 'duration_ms': current.duration_ms})
        return current
    except ProviderFailure as error:
        code = error.code
    except Exception:
        # No se registran reportes, respuesta del proveedor ni excepciones con credenciales.
        code = 'analysis_failed'
    # Una caída del proveedor no debe ocultar peligros explícitos del reporte.
    safe_priority = PriorityLevel.objects.filter(is_active=True, rank__gte=floor).order_by('rank').first() if floor else None
    active_codes = {f['rule'] for f in findings if f['active']}
    safe_actions = list(dict.fromkeys(action for rule in rules if rule.code in active_codes
        for action in rule.conditions.get('safe_actions', [])))[:8]
    IncidentAIAnalysis.objects.filter(pk=job.pk, execution_status='RUNNING').update(
        execution_status='FAILED', error_code=code, finished_at=timezone.now(),
        raw_output=original, safety_findings=findings, suggested_priority=safe_priority,
        risk_score=score if floor else None, suggested_action='\n'.join(safe_actions),
        duration_ms=int((monotonic() - started) * 1000))
    job.refresh_from_db()
    record_audit_event(action_code='INCIDENT_AI_FAILED', resource_type='IncidentAIAnalysis', resource_id=job.pk,
                       actor_user=job.requested_by, after_data={'error_code': code})
    return job


@transaction.atomic
def review_analysis(analysis, user, category, priority, reason, safety_override=False):
    if not can_review(user):
        raise PermissionDenied('No tienes permiso para revisar este análisis.')
    incident = Incident.objects.select_for_update(of=('self',)).select_related('sector').get(pk=analysis.incident_id)
    analysis = IncidentAIAnalysis.objects.select_for_update().get(pk=analysis.pk)
    if analysis.execution_status not in ('SUCCEEDED', 'FAILED'):
        raise ValidationError('Espera a que termine el análisis.')
    if analysis.review_status != 'PENDING':
        raise ValidationError('Este análisis ya fue revisado. Solicita uno nuevo si cambió la información.')
    if incident.ai_analyses.order_by('-id').values_list('pk', flat=True).first() != analysis.pk:
        raise ValidationError('Hay un análisis más reciente. Revisa la propuesta actual.')
    current_snapshot = snapshot(incident)
    if 'images' not in analysis.input_snapshot:
        current_snapshot.pop('images')
    if analysis.text_hash != fingerprint(current_snapshot):
        raise ValidationError('El reporte cambió. Solicita un análisis actualizado.')
    _, floor, _ = evaluate(incident.title + '\n' + incident.description, RiskRule.objects.filter(is_active=True))
    floor = max(floor, max((f.get('min_rank', 0) for f in analysis.safety_findings if f.get('active') and f.get('source') == 'image'), default=0))
    if priority.rank < floor and not (safety_override and len(reason.strip()) >= 20):
        raise ValidationError({'priority': 'Las señales de seguridad requieren una prioridad mayor. Para corregir un falso positivo, confirma la excepción y explica el motivo (20 caracteres).'} )
    review = IncidentAIReview.objects.create(analysis=analysis, reviewer=user, category=category,
        priority=priority, reason=reason, safety_override=safety_override)
    before = {'category': incident.category_id, 'priority': incident.priority_id}
    incident.category = category
    incident.priority = priority
    # Una clasificación urgente puede adelantar el plazo, nunca retrasarlo automáticamente.
    if priority.target_minutes:
        due = incident.created_at + timedelta(minutes=priority.target_minutes)
        incident.due_at = min(incident.due_at, due) if incident.due_at else due
    incident.save(update_fields=('category', 'priority', 'due_at', 'updated_at'))
    analysis.review_status = 'ACCEPTED' if analysis.suggested_category_id == category.pk and analysis.suggested_priority_id == priority.pk else 'CORRECTED'
    analysis.reviewed_by_user = user
    analysis.reviewed_at = review.created_at
    analysis.save(update_fields=('review_status', 'reviewed_by_user', 'reviewed_at'))
    record_audit_event(action_code='INCIDENT_AI_REVIEW', resource_type='IncidentAIAnalysis', resource_id=analysis.pk,
        actor_user=user, before_data=before, after_data={'category': category.pk, 'priority': priority.pk, 'safety_override': safety_override})
    return analysis


def presentation(row, user):
    predicted = row.raw_output.get('validated_prediction', row.raw_output.get('prediction', {}))
    human = getattr(row, 'human_review', None)
    category = human.category if human else row.suggested_category
    priority = human.priority if human else row.suggested_priority
    data = {
        'id': row.pk, 'execution_status': row.execution_status, 'review_status': row.review_status,
        'model': row.model_name, 'model_version': row.model_version, 'created_at': row.created_at,
        'duration_ms': row.duration_ms, 'error_code': row.error_code,
        'category': {'id': category.pk, 'name': category.name} if category else None,
        'priority': {'id': priority.pk, 'name': priority.name, 'rank': priority.rank} if priority else None,
        'confidence': row.confidence, 'risk_score': row.risk_score,
        'summary': predicted.get('summary', ''), 'risks': predicted.get('risks', []),
        'recommendations': predicted.get('recommendations', row.suggested_action.splitlines()), 'safety_findings': row.safety_findings,
        'entities': list(row.entities.values('entity_type', 'text_value', 'normalized_value')),
        'media': row.raw_output.get('media', []),
        'can_analyze': can_analyze(user), 'can_review': can_review(user),
        'review': {'reason': human.reason, 'reviewed_at': human.created_at, 'reviewer': human.reviewer.person.full_name if human.reviewer else 'Usuario'} if human else None,
    }
    if can_review(user):
        data['original_prediction'] = row.raw_output.get('prediction')
    return data
