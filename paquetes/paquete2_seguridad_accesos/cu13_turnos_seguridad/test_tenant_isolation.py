"""Regresiones de aislamiento de turnos después de integrar SaaS."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Person, Role, User
from condominiums.models import Condominium, Staff
from security.models import SecurityShift, ShiftLogEntry, ShiftHandover
from tenancy.context import TenantContext
from tenancy.models import TenantMembership


class ShiftTenantIsolationTests(APITestCase):
    def setUp(self):
        TenantContext.clear()
        self.addCleanup(TenantContext.clear)
        self.a = Condominium.objects.create(name="A", slug="isolation-a")
        self.b = Condominium.objects.create(name="B", slug="isolation-b")
        self.role, _ = Role.objects.get_or_create(slug="administrador", defaults={"name": "Administrador"})
        self.admin = User.objects.create_user(email="admin-b@example.test", password="Test-only-123!", role=self.role)
        TenantMembership.objects.create(user=self.admin, condominium=self.b, role=self.role, is_default=True)
        self.guard_a = Staff.objects.create(person=Person.objects.create(first_name="Guardia", last_name="A"),
            condominium=self.a, staff_type=Staff.Type.SECURITY)
        self.guard_b = Staff.objects.create(person=Person.objects.create(first_name="Guardia", last_name="B"),
            condominium=self.b, staff_type=Staff.Type.SECURITY)
        self.start = timezone.now() + timedelta(days=1)
        self.client.force_authenticate(user=self.admin)

    def payload(self, **extra):
        return {"guard_staff": self.guard_b.pk, "scheduled_start": self.start.isoformat(),
                "scheduled_end": (self.start + timedelta(hours=1)).isoformat(), **extra}

    def test_creation_assigns_authenticated_tenant(self):
        response = self.client.post(reverse("turnos-seguridad-list"), self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["condominium"], self.b.pk)

    def test_cannot_choose_another_condominium(self):
        response = self.client.post(reverse("turnos-seguridad-list"),
            self.payload(condominium=self.a.pk), format="json")
        self.assertIn(response.status_code, (400, 403), response.data)

    def test_cannot_assign_guard_from_another_condominium(self):
        response = self.client.post(reverse("turnos-seguridad-list"),
            self.payload(guard_staff=self.guard_a.pk), format="json")
        self.assertIn(response.status_code, (400, 403), response.data)

    def test_admin_without_membership_cannot_read_tenant_shifts(self):
        SecurityShift.objects.create(guard_staff=self.guard_a, condominium=self.a,
            scheduled_start=self.start, scheduled_end=self.start + timedelta(hours=1))
        orphan = User.objects.create_user(email="orphan@example.test", password="Test-only-123!", role=self.role)
        self.client.force_authenticate(user=orphan)
        response = self.client.get(reverse("turnos-seguridad-list"))
        self.assertEqual(response.status_code, 403, response.data)

    def test_cannot_read_shift_of_another_condominium(self):
        shift = SecurityShift.objects.create(guard_staff=self.guard_a, condominium=self.a,
            scheduled_start=self.start, scheduled_end=self.start + timedelta(hours=1))
        response = self.client.get(reverse("turnos-seguridad-detail", args=[shift.pk]))
        self.assertEqual(response.status_code, 404, response.data)

    def test_all_shift_collections_exclude_other_tenants(self):
        now = timezone.now()
        for state in ("OPEN", "SCHEDULED", "CLOSED"):
            SecurityShift.objects.create(guard_staff=self.guard_a, condominium=self.a,
                scheduled_start=now + timedelta(days=1), scheduled_end=now + timedelta(days=1, hours=1), status=state)
        for action in ("list", "proximos", "historial"):
            with self.subTest(action=action):
                response = self.client.get(reverse(f"turnos-seguridad-{action}"))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data if isinstance(response.data, list) else response.data["results"], [])
        for query in ({}, {"guard": self.guard_a.pk}):
            response = self.client.get(reverse("turnos-seguridad-actual"), query)
            self.assertIsNone(response.data["shift"])

    def test_update_cannot_reassign_condominium_or_foreign_guard(self):
        response = self.client.post(reverse("turnos-seguridad-list"), self.payload(), format="json")
        path = reverse("turnos-seguridad-detail", args=[response.data["id"]])
        for data in ({"condominium": self.a.pk}, {"guard_staff": self.guard_a.pk}):
            with self.subTest(data=data):
                self.assertEqual(self.client.patch(path, data, format="json").status_code, 400)

    def test_membership_role_overrides_global_user_role(self):
        resident, _ = Role.objects.get_or_create(slug="residente", defaults={"name": "Residente"})
        TenantMembership.objects.filter(user=self.admin).update(role=resident)
        self.assertEqual(self.client.get(reverse("turnos-seguridad-list")).status_code, 403)

    def test_inactive_membership_or_tenant_is_denied(self):
        TenantMembership.objects.filter(user=self.admin).update(is_active=False)
        self.assertEqual(self.client.get(reverse("turnos-seguridad-list")).status_code, 403)
        TenantMembership.objects.filter(user=self.admin).update(is_active=True)
        self.b.is_active = False
        self.b.save()
        self.assertEqual(self.client.get(reverse("turnos-seguridad-list")).status_code, 403)

    def test_logs_and_handovers_do_not_expose_mismatched_legacy_shifts(self):
        outgoing = SecurityShift.objects.create(guard_staff=self.guard_b, condominium=self.a,
            scheduled_start=self.start, scheduled_end=self.start + timedelta(hours=1))
        incoming = SecurityShift.objects.create(guard_staff=self.guard_b, condominium=self.b,
            scheduled_start=self.start + timedelta(hours=1), scheduled_end=self.start + timedelta(hours=2))
        entry = ShiftLogEntry.objects.create(shift=outgoing, title="Ajeno", description="Ajeno")
        handover = ShiftHandover.objects.create(outgoing_shift=outgoing, incoming_shift=incoming, summary="Ajeno")
        for resource, pk in (("novedades-turno", entry.pk), ("entregas-turno", handover.pk)):
            path = f"/api/v1/security/{resource}/"
            with self.subTest(resource=resource):
                self.assertEqual(self.client.get(path).data["results"], [])
                self.assertEqual(self.client.get(f"{path}{pk}/").status_code, 404)

    def test_no_membership_denied_for_all_three_modules(self):
        TenantMembership.objects.filter(user=self.admin).delete()
        for path in (reverse("turnos-seguridad-list"), "/api/v1/security/novedades-turno/", "/api/v1/security/entregas-turno/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_security_lifecycle_with_real_bearer_authentication(self):
        role, _ = Role.objects.get_or_create(slug="seguridad", defaults={"name": "Seguridad"})
        second_staff = Staff.objects.create(person=Person.objects.create(first_name="Relevo", last_name="B"),
            condominium=self.b, staff_type="SECURITY")
        clients = []
        for index, staff in enumerate((self.guard_b, second_staff)):
            user = User.objects.create_user(email=f"guard-{index}@example.test", password="Test-only-123!", person=staff.person, role=role)
            TenantMembership.objects.create(user=user, condominium=self.b, role=role, is_default=True)
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
            clients.append(client)
        admin = APIClient()
        admin.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.admin)}")
        now = timezone.now()
        ids = []
        for staff, start, end in ((self.guard_b, now-timedelta(minutes=1), now+timedelta(minutes=2)),
                                  (second_staff, now+timedelta(minutes=2), now+timedelta(hours=1))):
            response = admin.post(reverse("turnos-seguridad-list"), {
                "guard_staff": staff.pk, "scheduled_start": start.isoformat(), "scheduled_end": end.isoformat(),
            }, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["condominium"], self.b.pk)
            ids.append(response.data["id"])
        self.assertEqual(clients[0].post(reverse("turnos-seguridad-iniciar", args=[ids[0]])).status_code, 200)
        note = clients[0].post("/api/v1/security/novedades-turno/", {
            "title": "Revisión", "description": "Revisar portón", "entry_type": "NOTE", "severity": "INFO",
        }, format="json")
        self.assertEqual(note.status_code, 201, note.data)
        self.assertEqual(note.data["condominium"], self.b.pk)
        delivery = clients[0].post("/api/v1/security/entregas-turno/", {
            "outgoing_shift": ids[0], "incoming_shift": ids[1], "summary": "Revisar portón",
        }, format="json")
        self.assertEqual(delivery.status_code, 201, delivery.data)
        path = f'/api/v1/security/entregas-turno/{delivery.data["id"]}/recibir/'
        self.assertEqual(clients[1].post(path).status_code, 400)
        self.assertEqual(clients[1].post(reverse("turnos-seguridad-iniciar", args=[ids[1]])).status_code, 200)
        self.assertEqual(clients[1].post(path).data["status"], "RECEIVED")
        self.assertEqual(admin.get("/api/v1/security/entregas-turno/").data["pagination"]["total_items"], 1)
        self.assertEqual(clients[0].get(reverse("turnos-seguridad-list"), HTTP_X_TENANT_ID=str(self.a.pk)).status_code, 403)
