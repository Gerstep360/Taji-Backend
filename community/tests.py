from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import User, Role, Person
from condominiums.models import Condominium, Resident, Sector
from tenancy.models import TenantMembership
from tenancy.context import TenantContext
from notifications.models import Announcement
from .models import CommonArea, Reservation, Assembly, Agreement, CommonAreaBlock


class MobileCommunityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Condominium.objects.create(name='Comunidad móvil A')
        cls.other = Condominium.objects.create(name='Comunidad móvil B')
        cls.admin = cls.make_user('admin-mobile@taji.test', 'administrador')
        cls.neighbor = cls.make_user('neighbor-mobile@taji.test', 'residente')
        cls.second = cls.make_user('second-mobile@taji.test', 'residente')
        cls.guard = cls.make_user('guard-mobile@taji.test', 'seguridad')
        cls.resident = Resident.objects.create(condominium=cls.tenant, person=cls.neighbor.person)
        cls.resident2 = Resident.objects.create(condominium=cls.tenant, person=cls.second.person)
        cls.area = CommonArea.objects.create(condominium=cls.tenant, name='Salón móvil A')
        cls.foreign_area = CommonArea.objects.create(condominium=cls.other, name='Salón móvil B')
        cls.foreign_sector = Sector.objects.create(condominium=cls.other, code='MOBILE-B',name='Sector ajeno')
    @classmethod
    def make_user(cls, email, role):
        person=Person.objects.create(first_name=email.split('@')[0],last_name='Prueba')
        user=User.objects.create_user(email=email,password='Testing-Mobile-123!',person=person,role=Role.objects.get(slug=role),is_approved=True)
        TenantMembership.objects.create(user=user,condominium=cls.tenant,role=user.role,is_default=True)
        return user
    def setUp(self):
        TenantContext.clear(); self.addCleanup(TenantContext.clear)
        self.client.force_authenticate(user=self.admin)
    def payload(self, **extra):
        start=timezone.now()+timedelta(days=2)
        return {'common_area':self.area.pk,'start_at':start.isoformat(),'end_at':(start+timedelta(hours=1)).isoformat(),**extra}
    def reserve(self, **extra):
        self.client.force_authenticate(user=self.neighbor)
        return self.client.post('/api/v1/community/reservations/', self.payload(**extra),format='json')
    def test_area_list_and_detail_are_tenant_scoped(self):
        response=self.client.get('/api/v1/community/areas/')
        self.assertEqual(response.status_code,200)
        self.assertEqual([r['id'] for r in response.data['results']],[self.area.pk])
        self.assertEqual(self.client.get(f'/api/v1/community/areas/{self.foreign_area.pk}/').status_code,404)
    def test_admin_can_create_edit_and_archive_area_without_deleting(self):
        response=self.client.post('/api/v1/community/areas/',{'name':'Jardín móvil','capacity':10},format='json')
        self.assertEqual(response.status_code,201,response.data)
        area=CommonArea.objects.get(pk=response.data['id']);self.assertEqual(area.condominium_id,self.tenant.pk)
        self.assertEqual(self.client.patch(f'/api/v1/community/areas/{area.pk}/',{'capacity':15},format='json').status_code,200)
        self.assertEqual(self.client.delete(f'/api/v1/community/areas/{area.pk}/').status_code,204)
        area.refresh_from_db();self.assertEqual(area.status,'INACTIVE')

    def test_condominium_configuration_only_reads_and_updates_current_tenant(self):
        url=f'/api/v1/community/condominium/{self.tenant.pk}/'
        self.assertEqual(self.client.patch(url, {'phone':'12345678'}, format='json').status_code,200)
        self.assertEqual(self.client.get(f'/api/v1/community/condominium/{self.other.pk}/').status_code,404)
        self.assertEqual(self.client.post('/api/v1/community/condominium/',{},format='json').status_code,405)
        self.client.force_authenticate(user=self.neighbor)
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.patch(url,{'phone':'000'},format='json').status_code,403)
    def test_invalid_capacity_and_foreign_sector_return_validation_errors(self):
        for payload in [{'name':'Inválida','capacity':0},{'name':'Ajena','sector':self.foreign_sector.pk}]:
            self.assertEqual(self.client.post('/api/v1/community/areas/',payload,format='json').status_code,400)
    def test_resident_can_reserve_only_for_themself(self):
        response=self.reserve()
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data['resident'],self.resident.pk)
        self.assertEqual(response.data['status'],'APPROVED')
        self.assertEqual(self.reserve(resident=self.resident2.pk).status_code,403)
    def test_overlaps_are_rejected_and_adjacent_slots_are_allowed(self):
        data=self.payload();self.client.force_authenticate(user=self.neighbor)
        first=self.client.post('/api/v1/community/reservations/',data,format='json')
        self.assertEqual(first.status_code,201,first.data)
        self.assertEqual(self.client.post('/api/v1/community/reservations/',data,format='json').status_code,400)
        start=timezone.now()+timedelta(days=2,hours=2)
        data.update(start_at=start.isoformat(),end_at=(start+timedelta(hours=1)).isoformat())
        self.assertEqual(self.client.post('/api/v1/community/reservations/',data,format='json').status_code,201)
    def test_resident_cannot_reserve_a_foreign_area_or_approve_their_reservation(self):
        self.assertEqual(self.reserve(common_area=self.foreign_area.pk).status_code,400)
        self.area.requires_approval=True;self.area.save()
        response=self.reserve(status='APPROVED')
        self.assertEqual(response.status_code,201,response.data);self.assertEqual(response.data['status'],'PENDING')
        self.assertEqual(self.client.patch(f"/api/v1/community/reservations/{response.data['id']}/",{'status':'APPROVED'},format='json').status_code,403)
    def test_owner_can_cancel_but_not_modify_another_residents_reservation(self):
        response=self.reserve(); url=f"/api/v1/community/reservations/{response.data['id']}/"
        self.client.force_authenticate(user=self.second)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.patch(url,{'status':'CANCELLED'},format='json').status_code,404)
        self.client.force_authenticate(user=self.neighbor)
        self.assertEqual(self.client.patch(url,{'status':'CANCELLED'},format='json').status_code,200)
        self.assertEqual(self.client.patch(url,{'status':'APPROVED'},format='json').status_code,400)
    def test_unavailable_area_and_maintenance_block_are_respected(self):
        self.area.status='MAINTENANCE';self.area.save()
        self.assertEqual(self.reserve().status_code,400)
        self.area.status='AVAILABLE';self.area.save()
        start=timezone.now()+timedelta(days=1)
        CommonAreaBlock.objects.create(common_area=self.area,blocked_from=start,blocked_until=start+timedelta(days=3),reason='Reparación')
        self.assertEqual(self.reserve().status_code,400)
    def test_resident_cannot_manage_areas_and_guard_cannot_reserve(self):
        self.client.force_authenticate(user=self.neighbor)
        self.assertEqual(self.client.post('/api/v1/community/areas/',{'name':'Prohibida'},format='json').status_code,403)
        self.client.force_authenticate(user=self.guard)
        self.assertEqual(self.client.post('/api/v1/community/reservations/',self.payload(),format='json').status_code,403)
    def test_announcements_hide_other_tenants_drafts_expired_and_other_audiences(self):
        for title,extra in [('Visible',{}),('Borrador',{'status':'DRAFT'}),('Ajeno',{'condominium':self.other}),('Solo guardias',{'audience':'SECURITY'}),('Vencido',{'expires_at':timezone.now()-timedelta(days=1)})]:
            Announcement.objects.create(title=title,body='Texto',**{'condominium':self.tenant,'status':'PUBLISHED',**extra})
        self.client.force_authenticate(user=self.neighbor)
        response=self.client.get('/api/v1/community/announcements/')
        self.assertEqual([r['title'] for r in response.data['results']],['Visible'])
    def test_assembly_and_agreement_crud_keep_tenant_and_validate_foreign_key(self):
        data={'title':'Asamblea móvil','scheduled_at':(timezone.now()+timedelta(days=5)).isoformat()}
        response=self.client.post('/api/v1/community/assemblies/',data,format='json')
        self.assertEqual(response.status_code,201,response.data)
        assembly=Assembly.objects.get(pk=response.data['id']);self.assertEqual(assembly.condominium_id,self.tenant.pk)
        self.assertEqual(self.client.post('/api/v1/community/agreements/',{'assembly':assembly.pk,'title':'Acuerdo','estimated_budget':'-1'},format='json').status_code,400)
        foreign=Assembly.objects.create(condominium=self.other,**data)
        self.assertEqual(self.client.post('/api/v1/community/agreements/',{'assembly':foreign.pk,'title':'Ajeno'},format='json').status_code,400)
        created=self.client.post('/api/v1/community/agreements/',{'assembly':assembly.pk,'title':'Revisar iluminación'},format='json')
        self.assertEqual(created.status_code,201,created.data)
        self.assertEqual(self.client.patch(f"/api/v1/community/agreements/{created.data['id']}/",{'status':'COMPLETED'},format='json').status_code,200)
        self.assertIsNotNone(Agreement.objects.get(pk=created.data['id']).completed_at)
    def test_inactive_role_and_unassigned_legacy_records_are_not_exposed(self):
        CommonArea.objects.create(name='Legacy sin condominio')
        self.admin.role.is_active=False;self.admin.role.save()
        self.assertEqual(self.client.get('/api/v1/community/areas/').status_code,403)

    def test_mobile_audit_is_read_only_and_tenant_scoped(self):
        from auditlog.models import AuditEvent
        own=AuditEvent.objects.create(condominium=self.tenant,action_code='OWN',resource_type='Example')
        AuditEvent.objects.create(condominium=self.other,action_code='FOREIGN',resource_type='Example')
        AuditEvent.objects.create(action_code='LEGACY_UNKNOWN',resource_type='Example')
        response=self.client.get('/api/v1/community/audit/')
        self.assertEqual(response.status_code,200)
        self.assertEqual([r['id'] for r in response.data['results']],[own.pk])
        self.assertEqual(self.client.post('/api/v1/community/audit/',{},format='json').status_code,405)
        self.client.force_authenticate(user=self.neighbor)
        self.assertEqual(self.client.get('/api/v1/community/audit/').status_code,403)

    def test_cancel_is_allowed_after_area_becomes_unavailable(self):
        response=self.reserve();self.area.status='MAINTENANCE';self.area.save()
        self.assertEqual(self.client.patch(f"/api/v1/community/reservations/{response.data['id']}/",{'status':'CANCELLED'},format='json').status_code,200)

    def test_invalid_area_id_is_not_a_server_error(self):
        self.assertEqual(self.reserve(common_area='invalid').status_code,400)
