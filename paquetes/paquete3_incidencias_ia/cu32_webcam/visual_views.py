from datetime import timedelta
from shutil import which

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied, Throttled, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from auditlog.services import record_audit_event
from condominiums.models import Sector
from incidents.models import Incident
from security.models import VisualObservation as Observation, VisualQuota, VisualSession
from tenancy.context import TenantContext

from .views import WebcamView
from .visual_jobs import IN_FLIGHT, SESSION_DURATION, STATE, WORKER_GRACE, close_session, provider_for
from .visual_media import IMAGE_MAX, VIDEO_MAX, clean_media
from .visual_reasoning import can_review, incident_scope, scoped_observations, visible_matches


class Unavailable(APIException):
    status_code = 503
    default_code = 'visual_unavailable'


class Conflict(APIException):
    status_code = 409
    default_code = 'visual_conflict'


class VisualView(WebcamView):
    # Polling and history are not charged against the independent plate throttle.
    throttle_classes = []

    def session(self, request, pk):
        return get_object_or_404(VisualSession.objects.select_for_update(), pk=pk, owner=request.user,
                                 condominium_id=TenantContext.get_current_tenant_id())

    def observation_scope(self, request):
        return scoped_observations(TenantContext.get_current_tenant_id(), request.user).select_related(
            'session__sector').defer('payload', 'evidence')


def active_modes(config):
    return [mode for mode in ('image', 'video') if config['ENABLED'] and provider_for(mode)
            and (mode == 'image' or (which(config['FFPROBE']) and which(config['FFMPEG'])))]


def worker_active(now):
    return VisualQuota.objects.filter(pk=1, worker_seen_at__gte=now - WORKER_GRACE).exists()


def presentation(job, user, *, detail=False):
    session = job.session
    result = {
        'id': job.pk, 'session_id': session.pk, 'camera_id': session.pk, 'mode': job.mode,
        'sector': {'id': session.sector_id, 'name': session.sector.name} if session.sector_id else None,
        'observed_from': job.observed_from, 'observed_until': job.observed_until, 'status': job.status,
        'provider_status': job.provider_error or job.status, 'provider_ms': job.provider_ms,
        'model_id': job.model_id, 'payload_bytes': job.payload_bytes,
    }
    if job.status == STATE.SUCCEEDED:
        result.update(description=job.description, prediction=job.prediction, review_status=job.review_status,
                      review_text=job.review_text, reviewed_at=job.reviewed_at, has_evidence=job.has_evidence)
        if detail:
            result['context_matches'] = visible_matches(job, user)
    return result


class SessionInput(serializers.Serializer):
    sector = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    keep_evidence = serializers.BooleanField(default=False)


class VisionSettingsView(VisualView):
    @extend_schema(responses={200: OpenApiResponse(description='Modos verificados, estado del worker, cuotas y sectores activos.')})
    def get(self, request):
        config = settings.TAJI_VISION
        sectors = Sector.objects.filter(condominium_id=TenantContext.get_current_tenant_id(), is_active=True)
        return Response({'modes': active_modes(config), 'worker_ready': worker_active(timezone.now()),
                         'can_review': can_review(request.user), 'interval': config['INTERVAL'],
                         'periodic': config['PERIODIC'], 'idle': max(config['IDLE'], config['PERIODIC']),
                         'session_per_hour': config['SESSION_PER_HOUR'], 'session_burst': config['SESSION_BURST'],
                         'retention_days': config['RETENTION_DAYS'], 'image_max_bytes': IMAGE_MAX,
                         'video_max_bytes': VIDEO_MAX, 'sectors': list(sectors.order_by('name', 'pk').values('id', 'name')[:500])})


class VisualSessionStartView(VisualView):
    @extend_schema(request=SessionInput, responses={201: OpenApiResponse(description='ID y vencimiento de la sesión.')})
    @transaction.atomic
    def post(self, request):
        inp = SessionInput(data=request.data)
        inp.is_valid(raise_exception=True)
        tenant_id = TenantContext.get_current_tenant_id()
        now = timezone.now()
        if not active_modes(settings.TAJI_VISION) or not worker_active(now):
            raise Unavailable('El análisis visual está desactivado o el trabajador aún no está listo.')
        sector_id = inp.validated_data.get('sector')
        if sector_id and not Sector.objects.filter(pk=sector_id, condominium_id=tenant_id, is_active=True).exists():
            raise ValidationError({'sector': 'Selecciona un sector activo de este condominio.'})
        VisualQuota.objects.select_for_update().get(pk=1)
        sessions = VisualSession.objects.select_for_update().filter(condominium_id=tenant_id, owner=request.user)
        if sessions.filter(started_at__gte=now - timedelta(minutes=1)).count() >= 6:
            raise Throttled(wait=60, detail='Espera antes de iniciar otra sesión.')
        for previous in sessions.filter(ended_at__isnull=True):
            close_session(previous, now)
        session = sessions.create(condominium_id=tenant_id, owner=request.user, sector_id=sector_id,
                                  keep_evidence=inp.validated_data['keep_evidence'], expires_at=now + SESSION_DURATION)
        record_audit_event(action_code='visual_session.started', resource_type='visual_session', resource_id=session.pk,
                           request=request, after_data={'sector': sector_id, 'keep_evidence': session.keep_evidence})
        return Response({'id': session.pk, 'expires_at': session.expires_at}, status=201)


class VisualSessionStopView(VisualView):
    @extend_schema(request=None, responses={204: None})
    @transaction.atomic
    def post(self, request, pk):
        session = self.session(request, pk)
        if session.ended_at is None:
            close_session(session, timezone.now())
            record_audit_event(action_code='visual_session.stopped', resource_type='visual_session',
                               resource_id=session.pk, request=request)
        return Response(status=204)


class WindowInput(serializers.Serializer):
    window = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=('image', 'video'))
    media = serializers.FileField()
    age_ms = serializers.IntegerField(required=False, default=0, min_value=0, max_value=18_000)


class VisualWindowView(VisualView):
    parser_classes = [MultiPartParser]

    @extend_schema(request=WindowInput, responses={202: OpenApiResponse(description='Ventana admitida para análisis asíncrono.')})
    @transaction.atomic
    def post(self, request, pk):
        length = request.META.get('CONTENT_LENGTH', '')
        if length.isdigit() and int(length) > VIDEO_MAX + 8192:
            raise ValidationError('La captura supera el tamaño máximo permitido.')
        inp = WindowInput(data=request.data)
        inp.is_valid(raise_exception=True)
        config = settings.TAJI_VISION
        data = inp.validated_data
        now = timezone.now()
        VisualQuota.objects.select_for_update().get_or_create(pk=1)
        session = self.session(request, pk)
        existing = session.observations.filter(window=data['window']).defer('payload', 'evidence').first()
        if existing:
            return Response(presentation(existing, request.user), status=202)
        if session.ended_at or session.expires_at <= now:
            raise Conflict('La sesión terminó. Inicia una nueva para continuar.')
        if data['mode'] not in active_modes(config) or not worker_active(now):
            raise Unavailable('El proveedor visual o su trabajador no está disponible.')
        if session.observations.filter(status__in=IN_FLIGHT).exists():
            raise Conflict('Todavía hay un análisis en curso.')
        if session.observations.filter(received_at__gt=now - timedelta(seconds=config['INTERVAL'])).exists():
            raise Throttled(wait=config['INTERVAL'], detail='Pausa entre capturas.')
        if session.observations.count() >= config['SESSION_PER_HOUR']:
            raise Throttled(wait=max(1, round((session.expires_at - now).total_seconds())), detail='Se alcanzó el límite de la sesión.')
        burst = Observation.objects.filter(session__owner=request.user, received_at__gt=now - timedelta(minutes=5))
        if burst.count() >= config['SESSION_BURST']:
            oldest = burst.order_by('received_at').values_list('received_at', flat=True).first()
            raise Throttled(wait=max(1, round((oldest + timedelta(minutes=5) - now).total_seconds()) + 1),
                            detail='Pausa por el límite de ráfaga de cinco minutos.')
        budget = Observation.objects.filter(received_at__gte=now - timedelta(minutes=1))
        if (budget.count() >= config['GLOBAL_PER_MIN']
                or budget.filter(session__condominium_id=session.condominium_id).count() >= config['TENANT_PER_MIN']
                or budget.filter(session__owner=request.user).count() >= config['USER_PER_MIN']):
            raise Throttled(wait=60, detail='Se alcanzó el presupuesto temporal de análisis.')
        if Observation.objects.filter(status__in=IN_FLIGHT).count() >= config['GLOBAL_PER_MIN']:
            raise Throttled(wait=30, detail='El trabajador está ocupado.')
        payload, duration = clean_media(data['media'], data['mode'])
        observed_until = now - timedelta(milliseconds=data['age_ms'])
        if observed_until - timedelta(seconds=duration) < session.started_at:
            raise ValidationError('La ventana no pertenece al intervalo de la sesión.')
        job = session.observations.create(window=data['window'], mode=data['mode'], payload=payload,
            payload_bytes=len(payload), observed_from=observed_until - timedelta(seconds=duration), observed_until=observed_until)
        return Response(presentation(job, request.user), status=202)


class HistoryInput(serializers.Serializer):
    sector = serializers.IntegerField(required=False, min_value=1)
    q = serializers.CharField(required=False, max_length=100, allow_blank=True)
    review = serializers.ChoiceField(required=False, choices=('pending', 'confirmed', 'corrected', 'dismissed', 'proposed'))
    relevance = serializers.ChoiceField(required=False, choices=('record', 'human_review'))
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)
    open_related = serializers.BooleanField(required=False)


class VisualPagination(PageNumberPagination):
    page_size = 10


class VisualHistoryView(VisualView):
    @extend_schema(parameters=[HistoryInput], responses={200: OpenApiResponse(description='Historial paginado de observaciones autorizadas.')})
    def get(self, request):
        inp = HistoryInput(data=request.query_params)
        inp.is_valid(raise_exception=True)
        scope = self.observation_scope(request).filter(status=STATE.SUCCEEDED).order_by('-observed_until', '-pk')
        mappings = {'sector': 'session__sector_id', 'review': 'review_status', 'since': 'observed_until__gte',
                    'until': 'observed_until__lte', 'relevance': 'prediction__suggested_action'}
        for key, value in inp.validated_data.items():
            if key in mappings:
                scope = scope.filter(**{mappings[key]: value})
            elif key == 'q' and value:
                for word in value.split()[:5]:
                    scope = scope.filter(Q(description__icontains=word) | Q(review_text__icontains=word) |
                                         Q(session__sector__name__icontains=word))
            elif key == 'open_related' and value:
                # Recheck the reader's current visibility and incident state, not the stored suggestion alone.
                candidates = list(scope.exclude(matches=[]).values_list('pk', 'matches')[:500])
                codes = {item['code'] for _, items in candidates for item in items}
                pending = set(incident_scope(request.user, TenantContext.get_current_tenant_id())
                              .filter(public_code__in=codes).exclude(status__in=(Incident.Status.RESOLVED,
                                      Incident.Status.CLOSED, Incident.Status.CANCELLED)).values_list('public_code', flat=True))
                scope = scope.filter(pk__in=[pk for pk, items in candidates if any(item['code'] in pending for item in items)])
        pagination = VisualPagination()
        page = pagination.paginate_queryset(scope, request, view=self)
        return pagination.get_paginated_response([presentation(job, request.user) for job in page])


class VisualDetailView(VisualView):
    @extend_schema(responses={200: OpenApiResponse(description='Estado del análisis o detalle de la observación.')})
    def get(self, request, pk):
        return Response(presentation(get_object_or_404(self.observation_scope(request), pk=pk), request.user, detail=True))


class VisualEvidenceView(VisualView):
    @extend_schema(responses={(200, 'image/jpeg'): bytes, (200, 'video/mp4'): bytes})
    def get(self, request, pk):
        job = get_object_or_404(self.observation_scope(request), pk=pk, has_evidence=True, status=STATE.SUCCEEDED,
                               observed_until__gte=timezone.now() - timedelta(days=settings.TAJI_VISION['RETENTION_DAYS']))
        response = HttpResponse(bytes(job.evidence), content_type='video/mp4' if job.mode == 'video' else 'image/jpeg')
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class ReviewInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=('confirmed', 'corrected', 'dismissed', 'proposed'))
    note = serializers.CharField(max_length=320, required=False, allow_blank=True)


class VisualReviewView(VisualView):
    @extend_schema(request=ReviewInput, responses={200: OpenApiResponse(description='Observación revisada sin modificar la predicción.')})
    @transaction.atomic
    def post(self, request, pk):
        if not can_review(request.user):
            raise PermissionDenied('No tienes permiso para revisar observaciones visuales.')
        inp = ReviewInput(data=request.data)
        inp.is_valid(raise_exception=True)
        decision = inp.validated_data['decision']
        note = inp.validated_data.get('note', '')
        if decision in ('corrected', 'dismissed', 'proposed') and not note:
            raise ValidationError({'note': 'Indica el motivo o la corrección.'})
        scope = self.observation_scope(request).select_related(None).select_for_update()
        job = get_object_or_404(scope, pk=pk, status=STATE.SUCCEEDED)
        previous = {'decision': job.review_status, 'note': job.review_text}
        job.review_status, job.review_text = decision, note
        job.reviewed_by, job.reviewed_at = request.user, timezone.now()
        job.save(update_fields=['review_status', 'review_text', 'reviewed_by', 'reviewed_at'])
        record_audit_event(action_code='visual_observation.reviewed', resource_type='visual_observation', resource_id=job.pk,
                           request=request, before_data=previous, after_data={'decision': decision, 'note': note})
        return Response(presentation(job, request.user, detail=True))
