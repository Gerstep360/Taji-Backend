"""Servicios de comunidad compartidos por clientes móviles y web, aislados por tenant."""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import filters, serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.models import User
from auditlog.services import record_audit_event
from condominiums.models import Condominium, Resident, Sector
from notifications.models import Announcement
from tenancy.context import TenantContext
from tenancy.models import TenantMembership
from tenancy.permissions import IsTenantMember
from .models import CommonArea, Reservation, CommonAreaBlock, Assembly, Agreement
from auditlog.views import AuditEventListView, CanViewAuditLog


def allowed(user, code):
    member = TenantContext.get_current_membership()
    if user.is_superuser:
        return True
    return bool(member and member.user_id == user.pk and member.is_active and member.role
        and member.role.is_active and member.role.permissions.filter(code=code, is_active=True).exists())


class CommunityMember(IsTenantMember):
    def has_permission(self, request, view):
        tenant, member = TenantContext.get_current_tenant(), TenantContext.get_current_membership()
        if not tenant or not tenant.is_active or not super().has_permission(request, view):
            return False
        return request.user.is_superuser or bool(member and member.user_id == request.user.pk
            and member.is_active and member.role and member.role.is_active)


class MobileAuditView(AuditEventListView):
    permission_classes = [IsAuthenticated, CommunityMember, CanViewAuditLog]
    def get_queryset(self):
        return super().get_queryset().filter(condominium_id=TenantContext.get_current_tenant_id())


class ScopedSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = TenantContext.get_current_tenant_id()
        scopes = {
            'sector': lambda: Sector.objects.all_tenants().filter(condominium_id=tenant, is_active=True),
            'resident': lambda: Resident.objects.all_tenants().filter(condominium_id=tenant, status='ACTIVE'),
            'common_area': lambda: CommonArea.objects.filter(condominium_id=tenant),
            'assembly': lambda: Assembly.objects.filter(condominium_id=tenant),
            'responsible_user': lambda: User.objects.filter(pk__in=TenantMembership.objects.filter(condominium_id=tenant, is_active=True).values('user_id'), is_active=True),
        }
        for field, scope in scopes.items():
            if field in self.fields and not self.fields[field].read_only:
                self.fields[field].queryset = scope()


class AreaSerializer(ScopedSerializer):
    def validate_capacity(self, value):
        if value is not None and value < 1:
            raise ValidationError('La capacidad debe ser mayor que cero.')
        return value
    sector_name = serializers.CharField(source='sector.name', read_only=True, default='')
    class Meta:
        model = CommonArea
        fields = ('id', 'name', 'description', 'sector', 'sector_name', 'capacity', 'requires_approval', 'status')


class MobileCondominiumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condominium
        fields = ('id', 'name', 'legal_name', 'address', 'phone', 'email', 'timezone', 'rules_summary')
        read_only_fields = ('id',)


class ReservationSerializer(ScopedSerializer):
    common_area_name = serializers.CharField(source='common_area.name', read_only=True)
    resident_name = serializers.CharField(source='resident.person.full_name', read_only=True)
    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.none(), required=False)
    class Meta:
        model = Reservation
        fields = ('id', 'common_area', 'common_area_name', 'resident', 'resident_name', 'start_at', 'end_at', 'status', 'purpose', 'created_at')
        read_only_fields = ('created_at',)

    def validate(self, data):
        user = self.context['request'].user
        manager = allowed(user, 'manage_reservations')
        area = data.get('common_area', getattr(self.instance, 'common_area', None))
        if not area:
            raise ValidationError({'common_area': 'Selecciona un área común.'})
        resident = data.get('resident', getattr(self.instance, 'resident', None))
        if resident is None:
            resident = self.fields['resident'].queryset.filter(person_id=user.person_id).first()
        if not resident:
            raise ValidationError({'resident': 'Selecciona un residente activo del condominio.'})
        if not manager and resident.person_id != user.person_id:
            raise PermissionDenied('Solo puedes reservar a tu nombre.')
        start = data.get('start_at', getattr(self.instance, 'start_at', None))
        end = data.get('end_at', getattr(self.instance, 'end_at', None))
        if not start or not end or end <= start:
            raise ValidationError({'end_at': 'La hora final debe ser posterior a la inicial.'})
        if not self.instance or 'start_at' in data or 'end_at' in data:
            if start <= timezone.now():
                raise ValidationError({'start_at': 'Selecciona una fecha futura.'})
        status = data.get('status', getattr(self.instance, 'status', 'PENDING'))
        if self.instance:
            if area.pk != self.instance.common_area_id or resident.pk != self.instance.resident_id:
                raise ValidationError('Para cambiar el área o el residente, cancela esta reserva y crea otra.')
            if not manager and set(self.initial_data) - {'status'}:
                raise PermissionDenied('Para cambiar el horario, cancela la reserva y crea otra.')
            transitions = {'PENDING': {'PENDING','APPROVED','REJECTED','CANCELLED'}, 'APPROVED': {'APPROVED','COMPLETED','CANCELLED'}}
            if status not in transitions.get(self.instance.status, set()):
                raise ValidationError({'status': 'Esta reserva está cerrada o la transición no es válida.'})
            if not manager and (status != 'CANCELLED' or self.instance.start_at <= timezone.now()):
                raise PermissionDenied('Solo puedes cancelar tu reserva antes de que comience.')
        elif not manager:
            status = 'PENDING' if area.requires_approval else 'APPROVED'
        if status in ('PENDING', 'APPROVED'):
            if area.status != 'AVAILABLE':
                raise ValidationError({'common_area': 'El área no está disponible para reservar.'})
            overlaps = Reservation.objects.filter(common_area=area, status__in=('PENDING','APPROVED'), start_at__lt=end, end_at__gt=start)
            if self.instance:
                overlaps = overlaps.exclude(pk=self.instance.pk)
            if overlaps.exists() or CommonAreaBlock.objects.filter(common_area=area, blocked_from__lt=end, blocked_until__gt=start).exists():
                raise ValidationError('El horario ya está reservado o bloqueado. Elige otro horario.')
            schedules = area.schedules.filter(is_active=True)
            if schedules.exists():
                local_start, local_end = timezone.localtime(start), timezone.localtime(end)
                if local_start.date() != local_end.date() or not schedules.filter(weekday=local_start.weekday(), opens_at__lte=local_start.time(), closes_at__gte=local_end.time()).exists():
                    raise ValidationError('El horario está fuera de la disponibilidad del área.')
        data.update(resident=resident, status=status)
        return data


class AssemblySerializer(ScopedSerializer):
    class Meta:
        model = Assembly
        fields = ('id','title','description','scheduled_at','location','status','minutes_text','created_at')
        read_only_fields = ('created_at',)


class AgreementSerializer(ScopedSerializer):
    assembly_title = serializers.CharField(source='assembly.title', read_only=True)
    class Meta:
        model = Agreement
        fields = ('id','assembly','assembly_title','title','description','due_at','status','estimated_budget','actual_cost','completed_at')
        read_only_fields = ('completed_at',)
        extra_kwargs = {'estimated_budget': {'min_value': 0}, 'actual_cost': {'min_value': 0}}


class AnnouncementSerializer(ScopedSerializer):
    class Meta:
        model = Announcement
        fields = ('id','title','body','audience','priority','published_at','expires_at','status')
    def validate(self, data):
        start = data.get('published_at', getattr(self.instance, 'published_at', None))
        end = data.get('expires_at', getattr(self.instance, 'expires_at', None))
        if start and end and end <= start:
            raise ValidationError({'expires_at': 'El vencimiento debe ser posterior a la publicación.'})
        return data


class CommunityViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, CommunityMember]
    filter_backends = [filters.SearchFilter]
    search_fields = ('name',)
    manage_permission = 'manage_settings'
    tenant_lookup = 'condominium_id'
    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.serializer_class.Meta.model.objects.none()
        tenant = TenantContext.get_current_tenant()
        if not tenant or not tenant.is_active:
            return self.serializer_class.Meta.model.objects.none()
        return self.serializer_class.Meta.model.objects.filter(**{self.tenant_lookup: tenant.pk}).order_by('-pk')
    def require_manager(self):
        if not allowed(self.request.user, self.manage_permission):
            raise PermissionDenied('No tienes permiso para administrar este módulo.')
    def perform_create(self, serializer):
        self.require_manager()
        values = {'condominium_id': TenantContext.get_current_tenant_id()}
        if any(field.name == 'created_by_user' for field in serializer.Meta.model._meta.fields):
            values['created_by_user'] = self.request.user
        self.audit(serializer.save(**values), 'CREATED')
    def perform_update(self, serializer):
        self.require_manager()
        self.audit(serializer.save(), 'UPDATED')
    def audit(self, obj, action):
        record_audit_event(action_code='COMMUNITY_'+action, resource_type=obj.__class__.__name__, resource_id=obj.pk, actor_user=self.request.user, request=self.request)
    def destroy(self, request, *args, **kwargs):
        self.require_manager()
        obj = self.get_object()
        obj.status = {'CommonArea': 'INACTIVE', 'Announcement': 'ARCHIVED', 'Assembly': 'CANCELLED', 'Agreement': 'CANCELLED'}[obj.__class__.__name__]
        obj.save(update_fields=['status'])
        self.audit(obj, 'CLOSED')
        return Response(status=204)


class CommonAreaViewSet(CommunityViewSet):
    serializer_class = AreaSerializer
    manage_permission = 'manage_reservations'


class CondominiumViewSet(CommunityViewSet):
    serializer_class = MobileCondominiumSerializer
    http_method_names = ['get', 'patch', 'head', 'options']
    def get_queryset(self):
        return Condominium.objects.filter(pk=TenantContext.get_current_tenant_id(), is_active=True)


class ReservationViewSet(CommunityViewSet):
    serializer_class = ReservationSerializer
    search_fields = ('purpose', 'common_area__name')
    manage_permission = 'manage_reservations'
    tenant_lookup = 'common_area__condominium_id'
    def get_queryset(self):
        qs = super().get_queryset().select_related('resident__person', 'common_area')
        if getattr(self, 'swagger_fake_view', False):
            return qs
        if not allowed(self.request.user, self.manage_permission):
            qs = qs.filter(resident__person_id=self.request.user.person_id)
        return qs
    def create(self, request, *args, **kwargs):
        if not (allowed(request.user, self.manage_permission) or allowed(request.user, 'reserve_areas')):
            raise PermissionDenied('No tienes permiso para reservar áreas.')
        try:
            with transaction.atomic():
                key = str(request.data.get('common_area', ''))
                if not key.isascii() or not key.isdigit() or not 0 < len(key) <= 19 or not 0 < int(key) <= 9223372036854775807:
                    raise ValidationError({'common_area': 'Selecciona un área común válida.'})
                CommonArea.objects.select_for_update().filter(pk=key, condominium_id=TenantContext.get_current_tenant_id()).first()
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            raise ValidationError('El horario acaba de ser reservado. Elige otro.') from None
    def perform_create(self, serializer):
        self.audit(serializer.save(created_by_user=self.request.user), 'CREATED')
    def perform_update(self, serializer):
        obj = serializer.save()
        if obj.status in ('APPROVED','REJECTED') and allowed(self.request.user, self.manage_permission):
            obj.approved_by_user, obj.approved_at = self.request.user, timezone.now()
            obj.save(update_fields=['approved_by_user','approved_at'])
        if obj.status == 'CANCELLED':
            obj.cancelled_at = timezone.now(); obj.save(update_fields=['cancelled_at'])
        self.audit(obj, 'UPDATED')
    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                instance = self.get_object()
                CommonArea.objects.select_for_update().get(pk=instance.common_area_id)
                return super().update(request, *args, **kwargs)
        except IntegrityError:
            raise ValidationError('El horario acaba de ser reservado. Elige otro.') from None
    def destroy(self, request, *args, **kwargs):
        raise PermissionDenied('Cancela la reserva para conservar su historial.')


class AssemblyViewSet(CommunityViewSet):
    serializer_class = AssemblySerializer
    search_fields = ('title','description')
    def get_queryset(self):
        qs = super().get_queryset()
        return qs if allowed(self.request.user, 'manage_settings') or allowed(self.request.user, 'track_assembly_decisions') else qs.filter(status__in=('SCHEDULED','IN_PROGRESS','FINISHED'))


class AgreementViewSet(CommunityViewSet):
    serializer_class = AgreementSerializer
    search_fields = ('title','description')
    tenant_lookup = 'assembly__condominium_id'
    def perform_create(self, serializer):
        self.require_manager(); self.audit(serializer.save(), 'CREATED')
    def perform_update(self, serializer):
        self.require_manager()
        status = serializer.validated_data.get('status', serializer.instance.status)
        completed_at = (serializer.instance.completed_at or timezone.now()) if status == 'COMPLETED' else None
        obj = serializer.save(completed_at=completed_at)
        self.audit(obj, 'UPDATED')


class AnnouncementViewSet(CommunityViewSet):
    serializer_class = AnnouncementSerializer
    search_fields = ('title','body')
    manage_permission = 'manage_announcements'
    def get_queryset(self):
        qs = super().get_queryset()
        if allowed(self.request.user, self.manage_permission):
            return qs
        member = TenantContext.get_current_membership()
        role = member.role.slug if member and member.role else ''
        audience = {'residente':'RESIDENTS', 'seguridad':'SECURITY', 'mantenimiento':'MAINTENANCE', 'directiva':'DIRECTIVE'}.get(role)
        audiences = ['ALL'] + ([audience] if audience else [])
        if role in ('seguridad','mantenimiento','limpieza'):
            audiences.append('STAFF')
        return qs.filter(status='PUBLISHED', audience__in=audiences).filter(Q(published_at__isnull=True) | Q(published_at__lte=timezone.now())).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
    def perform_create(self, serializer):
        if serializer.validated_data.get('status') == 'PUBLISHED' and not serializer.validated_data.get('published_at'):
            serializer.validated_data['published_at'] = timezone.now()
        super().perform_create(serializer)
    def perform_update(self, serializer):
        status = serializer.validated_data.get('status', serializer.instance.status)
        if status == 'PUBLISHED' and not serializer.validated_data.get('published_at', serializer.instance.published_at):
            serializer.validated_data['published_at'] = timezone.now()
        super().perform_update(serializer)
