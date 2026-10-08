from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import Person, Role, User
from auditlog.models import AuditEvent
from condominiums.models import Condominium, Staff
from security.models import SecurityShift, ShiftLogEntry
from tenancy.models import TenantMembership


class ShiftLogTests(APITestCase):
    url = "/api/v1/security/novedades-turno/"

    @classmethod
    def setUpTestData(cls):
        cls.admin = cls.make_user("administrador", "admin")
        cls.guard = cls.make_user("seguridad", "guard")
        cls.other = cls.make_user("seguridad", "other")
        cls.resident = cls.make_user("residente", "resident")
        cls.staff = Staff.objects.create(person=cls.guard.person, staff_type="SECURITY", status="ACTIVE")
        cls.other_staff = Staff.objects.create(person=cls.other.person, staff_type="SECURITY", status="ACTIVE")
        cls.condo = Condominium.objects.create(name="Bosque")
        cls.other_condo = Condominium.objects.create(name="Flores")
        for user, condo in ((cls.admin, cls.condo), (cls.guard, cls.condo),
                            (cls.other, cls.other_condo), (cls.resident, cls.condo)):
            TenantMembership.objects.create(user=user, condominium=condo, role=user.role, is_default=True)
        cls.staff.condominium = cls.condo
        cls.staff.save()
        cls.other_staff.condominium = cls.other_condo
        cls.other_staff.save()
        now = timezone.now()
        cls.shift = SecurityShift.objects.create(guard_staff=cls.staff, condominium=cls.condo,
            status="OPEN", scheduled_start=now-timedelta(hours=10), scheduled_end=now-timedelta(hours=2), opened_at=now-timedelta(hours=10))
        cls.other_shift = SecurityShift.objects.create(guard_staff=cls.other_staff, condominium=cls.other_condo,
            status="OPEN", scheduled_start=now, scheduled_end=now+timedelta(hours=8), opened_at=now)
        cls.entry = ShiftLogEntry.objects.create(shift=cls.shift, created_by_user=cls.guard,
            title="Puerta", description="Revisión", entry_type="NOTE", severity="INFO")
        cls.other_entry = ShiftLogEntry.objects.create(shift=cls.other_shift, created_by_user=cls.other,
            title="Alerta", description="Puerta abierta", entry_type="ALERT", severity="HIGH")

    @classmethod
    def make_user(cls, slug, name):
        role, _ = Role.objects.get_or_create(slug=slug, defaults={"name": slug})
        person = Person.objects.create(first_name=name, last_name="Prueba", document_number=name)
        return User.objects.create_user(email=f"{name}@taji.test", password="Password123!",
            person=person, role=role, is_approved=True)

    def login(self, user=None):
        self.client.force_authenticate(user=user or self.guard)

    def payload(self, **extra):
        return {"entry_type": "INCIDENT", "severity": "HIGH", "title": "  Portón  ",
                "description": "  No se cierra correctamente.  ", **extra}

    def test_guard_registers_on_overdue_open_shift_with_server_identity_and_time(self):
        self.login()
        before = timezone.now()
        response = self.client.post(self.url, self.payload(shift=self.other_shift.id,
            created_by_user=self.other.id, occurred_at="2000-01-01T00:00:00Z", condominium=self.other_condo.id), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        entry = ShiftLogEntry.objects.get(pk=response.data["id"])
        self.assertEqual(entry.shift, self.shift)
        self.assertEqual(entry.created_by_user, self.guard)
        self.assertGreaterEqual(entry.occurred_at, before)
        self.assertEqual(entry.title, "Portón")
        self.assertEqual(response.data["condominium"], self.condo.id)
        self.assertTrue(AuditEvent.objects.filter(action_code="SHIFT_LOG_CREATED", resource_id=str(entry.pk)).exists())

    def test_guard_only_reads_own_records_including_closed_shift(self):
        self.shift.status = "CLOSED"
        self.shift.save()
        self.login()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.entry.pk])
        self.assertEqual(self.client.get(f"{self.url}{self.other_entry.pk}/").status_code, 404)

    def test_guard_cannot_filter_into_other_guard_data(self):
        self.login()
        self.assertEqual(self.client.get(self.url, {"guard": self.other_staff.pk}).data["results"], [])

    def test_admin_reads_filters_but_cannot_register(self):
        self.login(self.admin)
        response = self.client.get(self.url, {"entry_type": "ALERT", "severity": "HIGH", "guard": self.other_staff.pk,
            "shift": self.other_shift.pk, "condominium": self.other_condo.pk, "search": "abierta"})
        self.assertEqual(response.data["results"], [])
        own = self.client.get(self.url, {"guard": self.staff.pk, "search": "Revisión"})
        self.assertEqual([item["id"] for item in own.data["results"]], [self.entry.pk])
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)

    def test_no_open_shift_blocks_registration(self):
        self.shift.status = "CLOSED"
        self.shift.save()
        self.login()
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("shift", response.data["error"]["fields"])

    def test_inactive_staff_cannot_register(self):
        self.staff.status = "SUSPENDED"
        self.staff.save()
        self.login()
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)

    def test_stale_form_does_not_attach_to_another_shift(self):
        self.login()
        self.assertEqual(self.client.post(self.url, self.payload(expected_shift=self.other_shift.pk), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, self.payload(expected_shift=self.shift.pk), format="json").status_code, 201)

    def test_role_without_staff_cannot_register(self):
        self.login(self.make_user("seguridad", "no-staff"))
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)

    def test_resident_and_guest_denied(self):
        self.login(self.resident)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_invalid_fields_do_not_create_records(self):
        self.login()
        count = ShiftLogEntry.objects.count()
        for data in [self.payload(title="   "), self.payload(description=""), self.payload(entry_type="HANDOVER_NOTE"),
                     self.payload(severity="URGENT"), self.payload(title="x"*121), self.payload(description="x"*5001)]:
            self.assertEqual(self.client.post(self.url, data, format="json").status_code, 400)
        self.assertEqual(ShiftLogEntry.objects.count(), count)

    def test_invalid_query_returns_validation_error(self):
        self.login(self.admin)
        for query in [{"shift": "abc"}, {"date_from": "invalid"}, {"date_from": "2026-10-07", "date_to": "2026-10-06"}]:
            self.assertEqual(self.client.get(self.url, query).status_code, 400)

    def test_records_are_immutable(self):
        self.login()
        detail = f"{self.url}{self.entry.pk}/"
        self.assertEqual(self.client.patch(detail, {"title": "Alterado"}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(detail).status_code, 405)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.title, "Puerta")

    def test_handover_notes_are_not_exposed_as_cu14(self):
        ShiftLogEntry.objects.create(shift=self.shift, entry_type="HANDOVER_NOTE", description="Entrega")
        self.login()
        self.assertEqual(self.client.get(self.url).data["pagination"]["total_items"], 1)

    def test_alias_and_date_filters(self):
        self.login(self.admin)
        today = timezone.localdate().isoformat()
        response = self.client.get("/api/v1/paquete2/novedades-turno/", {"date_from": today, "date_to": today})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pagination"]["total_items"], 1)
