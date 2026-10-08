from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import Person, Role, User
from auditlog.models import AuditEvent
from condominiums.models import Condominium, Staff
from security.models import SecurityShift, ShiftHandover, ShiftLogEntry
from tenancy.models import TenantMembership


class HandoverTests(APITestCase):
    url = "/api/v1/security/entregas-turno/"
    @classmethod
    def setUpTestData(cls):
        cls.condo = Condominium.objects.create(name="Bosque")
        cls.other_condo = Condominium.objects.create(name="Flores")
        cls.guards = []
        cls.staff = []
        role, _ = Role.objects.get_or_create(slug="seguridad", defaults={"name": "Seguridad"})
        admin_role, _ = Role.objects.get_or_create(slug="administrador", defaults={"name": "Admin"})
        resident_role, _ = Role.objects.get_or_create(slug="residente", defaults={"name": "Residente"})
        for index in range(3):
            person = Person.objects.create(first_name=f"Guardia {index}", last_name="Prueba", document_number=str(index))
            user = User.objects.create_user(email=f"g{index}@test.com", password="Test12345!", person=person, role=role, is_approved=True)
            cls.guards.append(user)
            cls.staff.append(Staff.objects.create(person=person, condominium=cls.condo, staff_type="SECURITY", status="ACTIVE"))
            TenantMembership.objects.create(user=user, condominium=cls.condo, role=role, is_default=True)
        cls.admin = User.objects.create_user(email="admin@test.com", password="Test12345!", role=admin_role, is_approved=True)
        cls.resident = User.objects.create_user(email="resident@test.com", password="Test12345!", role=resident_role, is_approved=True)
        for user in (cls.admin, cls.resident):
            TenantMembership.objects.create(user=user, condominium=cls.condo, role=user.role, is_default=True)
        end = timezone.now() + timedelta(minutes=1)
        cls.outgoing = SecurityShift.objects.create(guard_staff=cls.staff[0], condominium=cls.condo,
            scheduled_start=end-timedelta(hours=8), scheduled_end=end, status="OPEN", opened_at=end-timedelta(hours=8))
        cls.incoming = SecurityShift.objects.create(guard_staff=cls.staff[1], condominium=cls.condo,
            scheduled_start=end+timedelta(minutes=1), scheduled_end=end+timedelta(hours=8), status="SCHEDULED")
        cls.log = ShiftLogEntry.objects.create(shift=cls.outgoing, title="Portón", description="Pendiente revisión", entry_type="ALERT")

    def login(self, index=0):
        self.client.force_authenticate(self.guards[index])
    def payload(self, **changes):
        return {"outgoing_shift": self.outgoing.pk, "incoming_shift": self.incoming.pk, "summary": "  Revisar portón  ", **changes}
    def deliver(self):
        self.login()
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]
    def open_incoming(self):
        self.incoming.status = "OPEN"; self.incoming.opened_at = timezone.now(); self.incoming.save()
    def test_delivery_preserves_manual_shift_lifecycle_and_server_identity(self):
        pk = self.deliver()
        obj = ShiftHandover.objects.get(pk=pk)
        self.assertEqual(obj.summary, "Revisar portón")
        self.assertEqual(obj.delivered_by_user, self.guards[0])
        self.assertIsNone(obj.received_at)
        self.outgoing.refresh_from_db(); self.incoming.refresh_from_db()
        self.assertEqual(self.outgoing.status, "OPEN"); self.assertEqual(self.incoming.status, "SCHEDULED")
        self.assertTrue(AuditEvent.objects.filter(action_code="SHIFT_HANDOVER_DELIVERED").exists())
    def test_candidates_exact_tolerance_boundaries_and_multiple_relay_choices(self):
        self.login()
        for minute in (-16, -15, 15, 16):
            self.incoming.scheduled_start = self.outgoing.scheduled_end + timedelta(minutes=minute); self.incoming.save()
            data = self.client.get(self.url+"candidatos/", {"outgoing_shift": self.outgoing.pk})
            self.assertEqual(data.status_code, 200)
            self.assertEqual(len(data.data), 1 if abs(minute) <= 15 else 0)
        self.incoming.scheduled_start = self.outgoing.scheduled_end; self.incoming.save()
        SecurityShift.objects.create(guard_staff=self.staff[2], condominium=self.condo, scheduled_start=self.outgoing.scheduled_end,
                                    scheduled_end=self.incoming.scheduled_end)
        self.assertEqual(len(self.client.get(self.url+"candidatos/", {"outgoing_shift": self.outgoing.pk}).data), 2)
    def test_midnight_is_compared_with_complete_timestamps(self):
        end = timezone.now().replace(hour=23, minute=59, second=0, microsecond=0)
        self.outgoing.scheduled_start = end-timedelta(hours=8); self.outgoing.scheduled_end = end; self.outgoing.save()
        self.incoming.scheduled_start = end+timedelta(minutes=2); self.incoming.scheduled_end = end+timedelta(hours=8); self.incoming.save()
        self.deliver()
    def test_cross_condominium_and_null_condominium_are_rejected(self):
        self.incoming.condominium = self.other_condo; self.incoming.save(); self.login()
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
        self.outgoing.condominium = None; self.outgoing.save()
        self.assertEqual(self.client.get(self.url+"candidatos/", {"outgoing_shift": self.outgoing.pk}).status_code, 404)
    def test_same_guard_and_inactive_guard_are_not_relay_candidates(self):
        self.incoming.guard_staff = self.staff[0]; self.incoming.save(); self.login()
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
        self.incoming.guard_staff = self.staff[1]; self.incoming.save()
        self.staff[1].status = "SUSPENDED"; self.staff[1].save()
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
    def test_closed_or_cancelled_incoming_rejected(self):
        self.login()
        for state in ("CLOSED", "CANCELLED"):
            self.incoming.status = state; self.incoming.save()
            self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
    def test_only_open_owned_outgoing_can_deliver(self):
        self.login(1)
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)
        self.assertEqual(self.client.get(self.url+"candidatos/", {"outgoing_shift": self.outgoing.pk}).status_code, 404)
        self.login(); self.outgoing.status = "CLOSED"; self.outgoing.save()
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
    def test_delivery_cannot_be_duplicated_or_modified(self):
        pk = self.deliver()
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"{self.url}{pk}/", {"summary": "Otro"}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(f"{self.url}{pk}/").status_code, 405)
        self.assertEqual(ShiftHandover.objects.count(), 1)
    def test_receiver_can_review_prior_logs_not_later_logs(self):
        pk = self.deliver()
        ShiftLogEntry.objects.create(shift=self.outgoing, description="Después", occurred_at=timezone.now()+timedelta(seconds=1))
        self.login(1)
        response = self.client.get(f"{self.url}{pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([e["id"] for e in response.data["log_entries"]], [self.log.pk])
    def test_only_designated_guard_receives_after_start_and_only_once(self):
        pk = self.deliver(); path = f"{self.url}{pk}/recibir/"
        self.assertEqual(self.client.post(path).status_code, 403)
        self.login(2); self.assertEqual(self.client.post(path).status_code, 404)
        self.login(1); self.assertEqual(self.client.post(path).status_code, 400)
        self.open_incoming()
        self.outgoing.status = "CLOSED"; self.outgoing.save()
        response = self.client.post(path, {"received_by_user": self.guards[2].pk}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["received_by_user"], self.guards[1].pk)
        self.assertEqual(response.data["status"], "RECEIVED")
        self.incoming.refresh_from_db(); self.assertEqual(self.incoming.status, "OPEN")
        self.assertEqual(self.client.post(path).status_code, 400)
        self.assertTrue(AuditEvent.objects.filter(action_code="SHIFT_HANDOVER_RECEIVED").exists())
    def test_admin_consults_but_cannot_receive_or_deliver(self):
        pk = self.deliver(); self.client.force_authenticate(self.admin)
        response = self.client.get(self.url, {"status": "PENDING", "guard": self.staff[1].pk})
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{self.url}{pk}/recibir/").status_code, 403)
    def test_unrelated_roles_and_guests_denied(self):
        self.client.force_authenticate(self.resident); self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None); self.assertIn(self.client.get(self.url).status_code, (401, 403))
    def test_empty_invalid_summary_and_filters_do_not_create(self):
        self.login()
        for summary in (" ", "x"*5001):
            self.assertEqual(self.client.post(self.url, self.payload(summary=summary), format="json").status_code, 400)
        for query in ({"guard": "abc"}, {"date_from": "bad"}, {"date_from": "2026-10-07", "date_to": "2026-10-06"}):
            self.assertEqual(self.client.get(self.url, query).status_code, 400)
    def test_cancelled_relay_after_delivery_cannot_receive(self):
        pk = self.deliver(); self.incoming.status = "CANCELLED"; self.incoming.save(); self.login(1)
        self.assertEqual(self.client.post(f"{self.url}{pk}/recibir/").status_code, 400)

    def test_missed_scheduled_relay_is_not_offered(self):
        end = timezone.now() - timedelta(hours=9)
        self.outgoing.scheduled_start = end-timedelta(hours=8); self.outgoing.scheduled_end = end; self.outgoing.save()
        self.incoming.scheduled_start = end; self.incoming.scheduled_end = end+timedelta(hours=8); self.incoming.save()
        self.login()
        self.assertEqual(self.client.get(self.url+"candidatos/", {"outgoing_shift": self.outgoing.pk}).data, [])
