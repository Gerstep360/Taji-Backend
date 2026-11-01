from datetime import timedelta
from uuid import uuid4
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from auditlog.services import record_audit_event
from incidents.models import IncidentAIAnalysis, IncidentCategory, PriorityLevel
from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.permissions import CanAccessIncidentTracking
from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.services import IncidentTrackingService
from .services import enqueue, presentation, can_analyze, can_review, review_analysis
from .serializers import ReviewSerializer, CategoryWriteSerializer, PriorityWriteSerializer


class AnalysisThrottle(UserRateThrottle):
    rate = '12/hour'


class IncidentAIView(APIView):
    permission_classes = [IsAuthenticated, CanAccessIncidentTracking]

    @extend_schema(responses={200: dict})
    def get(self, request, public_code):
        incident = IncidentTrackingService.get_incident_detail(public_code, request.user)
        rows = incident.ai_analyses.select_related('suggested_category', 'suggested_priority', 'human_review__category',
            'human_review__priority', 'human_review__reviewer__person').prefetch_related('entities').order_by('-id')[:5]
        return Response({'analyses': [presentation(row, request.user) for row in rows],
            'can_analyze': can_analyze(request.user), 'can_review': can_review(request.user)})

    @extend_schema(request=None, responses={202: dict})
    def post(self, request, public_code):
        throttle = AnalysisThrottle()
        if not throttle.allow_request(request, self):
            self.throttled(request, throttle.wait())
        incident = IncidentTrackingService.get_incident_detail(public_code, request.user)
        return Response(presentation(enqueue(incident, request.user), request.user), status=202)


class IncidentAIReviewView(APIView):
    permission_classes = [IsAuthenticated, CanAccessIncidentTracking]

    @extend_schema(request=ReviewSerializer, responses={200: dict})
    def post(self, request, public_code, analysis_id):
        incident = IncidentTrackingService.get_incident_detail(public_code, request.user)
        row = incident.ai_analyses.filter(pk=analysis_id).first()
        if not row:
            raise NotFound()
        data = ReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(presentation(review_analysis(row, request.user, **data.validated_data), request.user))


class IncidentAICatalogView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({
            'categories': CategoryWriteSerializer(IncidentCategory.objects.filter(is_active=True).order_by('name'), many=True).data,
            'priorities': PriorityWriteSerializer(PriorityLevel.objects.filter(is_active=True).order_by('rank'), many=True).data,
            'can_manage': request.user.is_superuser,
        })


class IncidentAICatalogWriteView(APIView):
    permission_classes = [IsAuthenticated]
    http_method_names = ['post', 'options']

    def _write(self, request, kind, pk=None):
        if not request.user.is_superuser:
            raise PermissionDenied('Los catálogos compartidos se administran desde la cuenta global.')
        if kind not in ('categories', 'priorities'):
            raise NotFound()
        model, serializer = (IncidentCategory, CategoryWriteSerializer) if kind == 'categories' else (PriorityLevel, PriorityWriteSerializer)
        instance = model.objects.filter(pk=pk).first() if pk else None
        if pk and not instance:
            raise NotFound()
        data = serializer(instance=instance, data=request.data, partial=pk is not None)
        data.is_valid(raise_exception=True)
        extra = {'code': (slugify(data.validated_data['name']).upper()[:38] or 'CATEGORY') + '_' + uuid4().hex[:8].upper()} if kind == 'categories' and not instance else {}
        row = data.save(**extra)
        record_audit_event(action_code='INCIDENT_AI_CATALOG_WRITE', resource_type=model.__name__, resource_id=row.pk, actor_user=request.user)
        return Response(serializer(row).data, status=200 if instance else 201)

    @extend_schema(request=dict, responses=dict)
    def post(self, request, kind):
        return self._write(request, kind)

    @extend_schema(request=dict, responses=dict)
    def patch(self, request, kind, pk):
        return self._write(request, kind, pk)


class IncidentAICatalogUpdateView(IncidentAICatalogWriteView):
    http_method_names = ['patch', 'options']


class IncidentAIMetricsView(APIView):
    permission_classes = [IsAuthenticated, CanAccessIncidentTracking]

    @extend_schema(responses=dict)
    def get(self, request):
        if not can_review(request.user):
            raise PermissionDenied()
        tenant_id = IncidentTrackingService.get_user_condominium_id(request.user)
        rows = IncidentAIAnalysis.objects.filter(incident__condominium_id=tenant_id,
            created_at__gte=timezone.now() - timedelta(days=30)) if tenant_id else IncidentAIAnalysis.objects.none()
        data = rows.aggregate(total=Count('id'), failed=Count('id', filter=Q(execution_status='FAILED')),
            reviewed=Count('id', filter=Q(review_status__in=('ACCEPTED', 'CORRECTED'))),
            accepted=Count('id', filter=Q(review_status='ACCEPTED')), mean_duration_ms=Avg('duration_ms'))
        data['acceptance_rate'] = round(data['accepted'] / data['reviewed'], 3) if data['reviewed'] else None
        return Response(data)
