from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from django.core.management import call_command
from auditlog.models import AuditEvent
from accounts.models import Person, User
from condominiums.models import Staff, Sector, Condominium
from maintenance.models import AssetType, Asset, MaintenancePlan
from incidents.models import Incident, IncidentAssignment
from notifications.models import Notification
from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.tests import IncidentTrackingTestCase, incident_url


class IncidentLifecycleTests(IncidentTrackingTestCase):
    def setUp(self):
        self.incident = self._make_incident()
        self.auth()

    def test_invalid_transition_does_not_write_history_or_status(self):
        response = self.client.post(incident_url(self.incident.public_code, "change-status"), {"status": "CLOSED"})
        self.assertEqual(response.status_code, 400)
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, "REPORTED")
        self.assertFalse(self.incident.status_history.exists())

    def test_transition_records_actor_history_and_audit(self):
        response = self.client.post(incident_url(self.incident.public_code, "change-status"), {"status": "REVIEWED", "comment": "Verificado"})
        self.assertEqual(response.status_code, 200, response.data)
        history = self.incident.status_history.get()
        self.assertEqual(history.changed_by_user, self.admin_user)
        self.assertEqual(history.from_status, "REPORTED")
        self.assertTrue(AuditEvent.objects.filter(action_code="INCIDENT_STATUS_CHANGE", resource_id=str(self.incident.pk)).exists())

    def test_other_tenant_and_unassigned_staff_cannot_read_detail(self):
        self.incident.condominium = self.other_condo
        self.incident.save()
        self.assertEqual(self.client.get(incident_url(self.incident.public_code)).status_code, 404)
        self.incident.condominium = self.condo
        self.incident.current_assignee_staff = None
        self.incident.save()
        self.auth(self.staff_person_user)
        self.assertEqual(self.client.get(incident_url(self.incident.public_code)).status_code, 404)

    def test_reassignment_closes_old_assignment_and_preserves_history(self):
        IncidentAssignment.objects.create(incident=self.incident, assigned_to_staff=self.staff_obj)
        staff = Staff.objects.create(person=Person.objects.create(first_name="Nuevo", last_name="Técnico"), condominium=self.condo, staff_type="MAINTENANCE")
        response = self.client.post(incident_url(self.incident.public_code, "assign"), {"staff_id": staff.pk})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.incident.assignments.filter(ended_at__isnull=True).count(), 1)
        self.assertEqual(self.incident.assignments.count(), 2)
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.current_assignee_staff, staff)
        self.assertEqual(self.incident.status, "ASSIGNED")

    def test_cross_tenant_assignment_is_rejected(self):
        self.staff_obj.condominium = self.other_condo
        self.staff_obj.save()
        response = self.client.post(incident_url(self.incident.public_code, "assign"), {"staff_id": self.staff_obj.pk})
        self.assertEqual(response.status_code, 400)

    def test_alerts_only_include_overdue_open_incidents_and_are_idempotent(self):
        self.incident.due_at = timezone.now() - timedelta(hours=1)
        self.incident.save()
        response = self.client.get('/api/v1/paquete3/incidents/alerts/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data[0]['code'], self.incident.public_code)
        call_command('generate_attention_alerts', verbosity=0)
        count = Notification.objects.count()
        self.assertGreater(count, 0)
        call_command('generate_attention_alerts', verbosity=0)
        self.assertEqual(count, Notification.objects.count())

    def test_reopening_clears_resolution_dates(self):
        self.incident.status = 'RESOLVED'
        self.incident.resolved_at = timezone.now()
        self.incident.save()
        response = self.client.post(incident_url(self.incident.public_code, 'change-status'), {'status': 'IN_PROGRESS'})
        self.assertEqual(response.status_code, 200, response.data)
        self.incident.refresh_from_db()
        self.assertIsNone(self.incident.resolved_at)

    def test_maintenance_alerts_respect_dates_activity_and_tenant(self):
        asset_type, _ = AssetType.objects.get_or_create(code='CU21', defaults={'name': 'Equipo CU21'})
        sector = Sector.objects.create(condominium=self.condo, code='CU21', name='Torre A', sector_type='TOWER')
        asset = Asset.objects.create(asset_type=asset_type, sector=sector, code='CU21-A', name='Ascensor')
        now = timezone.now()
        for name, days, active in [('Próximo', 2, True), ('Vencido', -2, True), ('Lejano', 30, True), ('Inactivo', -1, False)]:
            MaintenancePlan.objects.create(asset=asset, name=name, frequency_days=30, next_due_at=now + timedelta(days=days), is_active=active)
        response = self.client.get('/api/v1/paquete3/incidents/alerts/')
        self.assertEqual({row['title'] for row in response.data}, {'Próximo', 'Vencido'})
        sector.condominium = self.other_condo
        sector.save()
        self.assertEqual(self.client.get('/api/v1/paquete3/incidents/alerts/').data, [])

    def test_evidence_cannot_reference_another_incident_storage_path(self):
        response = self.client.post(incident_url(self.incident.public_code, 'attachments'), {'file_path': 'incidents/999/999/private.pdf'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.incident.attachments.exists())


@skipUnless(connection.vendor == 'postgresql', 'El bloqueo real de filas requiere PostgreSQL.')
class ConcurrentTransitionTests(TransactionTestCase):
    def test_two_operators_cannot_apply_the_same_transition_twice(self):
        from paquetes.paquete3_incidencias_ia.cu19_seguimiento_historial.services import IncidentTrackingService
        user = User.objects.create_user(email='cu21.concurrent@test.local', password='PruebaCU21!2026', first_name='Admin', last_name='Concurrente', is_superuser=True)
        incident = Incident.objects.create(condominium=Condominium.objects.create(name='Concurrente'), description='Prueba concurrente')
        barrier = Barrier(2)

        def change():
            try:
                stale_incident = Incident.objects.get(pk=incident.pk)
                actor = User.objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                try:
                    IncidentTrackingService.change_status(stale_incident, 'REVIEWED', actor)
                    return 'changed'
                except ValidationError:
                    return 'rejected'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: change(), range(2)))
        self.assertCountEqual(outcomes, ['changed', 'rejected'])
        self.assertEqual(incident.status_history.count(), 1)
