from datetime import datetime, timedelta, timezone

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Person, Role
from community.models import CommonArea, Reservation
from condominiums.models import Condominium, Resident, Sector, Unit
from incidents.models import Incident, PriorityLevel
from maintenance.models import WorkOrder
from security.models import AccessEvent, VisitAuthorization
from tenancy.models import TenantMembership


DAY = datetime(2026, 11, 22, 4, tzinfo=timezone.utc)


class DashboardTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Condominium.objects.create(name="Tenant A", slug="cu30-a")
        cls.b = Condominium.objects.create(name="Tenant B", slug="cu30-b")
        cls.empty = Condominium.objects.create(name="Tenant vacío", slug="cu30-empty")
        cls.admin_role = Role.objects.get(slug="administrador")
        cls.resident_role = Role.objects.get(slug="residente")
        cls.admin_a = cls.member("admin-a", cls.a, cls.admin_role)
        cls.admin_b = cls.member("admin-b", cls.b, cls.admin_role)
        cls.admin_empty = cls.member("admin-empty", cls.empty, cls.admin_role)
        cls.resident_user = cls.member("resident-a", cls.a, cls.resident_role)
        cls.platform = get_user_model().objects.create_superuser(
            email="platform-cu30@example.test", password="LocalTest123!"
        )
        cls.sector_a = Sector.objects.create(condominium=cls.a, name="Sector A", code="A")
        cls.sector_b = Sector.objects.create(condominium=cls.b, name="Sector B", code="B")
        cls.unit_a = Unit.objects.create(sector=cls.sector_a, code="CU30-A")
        cls.unit_b = Unit.objects.create(sector=cls.sector_b, code="CU30-B")
        cls.resident_a = Resident.objects.create(condominium=cls.a, person=cls.resident_user.person)
        resident_b = Resident.objects.create(condominium=cls.b, person=cls.admin_b.person)
        cls.area_a = CommonArea.objects.create(condominium=cls.a, sector=cls.sector_a, name="Área A")
        cls.area_b = CommonArea.objects.create(condominium=cls.b, sector=cls.sector_b, name="Área B")
        auth = VisitAuthorization.objects.create(
            visitor_person=cls.admin_a.person, authorized_by_resident=cls.resident_a,
            unit=cls.unit_a, valid_from=DAY, valid_until=DAY + timedelta(hours=2),
            qr_expires_at=DAY + timedelta(hours=2),
        )
        AccessEvent.objects.create(unit=cls.unit_a, authorization=auth, event_type="ENTRY", occurred_at=DAY)
        AccessEvent.objects.create(authorization=auth, event_type="DENIED", validation_result="REJECTED", occurred_at=DAY)
        AccessEvent.objects.create(unit=cls.unit_b, event_type="EXIT", occurred_at=DAY)
        AccessEvent.objects.create(unit=cls.unit_b, authorization=auth, event_type="ENTRY", occurred_at=DAY)
        AccessEvent.objects.create(event_type="ENTRY", occurred_at=DAY)
        AccessEvent.objects.create(unit=cls.unit_a, event_type="EXIT", occurred_at=DAY - timedelta(seconds=1))
        AccessEvent.objects.create(unit=cls.unit_a, event_type="EXIT", occurred_at=DAY + timedelta(days=1))

        priority = PriorityLevel.objects.first() or PriorityLevel.objects.create(code="CU30", name="CU30", rank=1)
        Incident.objects.create(condominium=cls.a, public_code="CU30-IA", priority=priority, created_at=DAY)
        incident_b = Incident.objects.create(
            condominium=cls.b, public_code="CU30-IB", status="RESOLVED", created_at=DAY
        )
        Incident.objects.create(condominium=cls.a, unit=cls.unit_b, public_code="CU30-IX", created_at=DAY)
        Incident.objects.create(public_code="CU30-I0", created_at=DAY)
        for tenant, code, status in ((cls.a, "A", "PENDING"), (cls.b, "B", "COMPLETED"), (cls.a, "C", "CANCELLED")):
            WorkOrder.objects.create(
                condominium=tenant, public_code=f"CU30-W{code}", work_type="CORRECTIVE",
                title=code, status=status, created_at=DAY, scheduled_for=DAY - timedelta(days=1),
            )
        WorkOrder.objects.create(
            condominium=cls.a, incident=incident_b, public_code="CU30-WX",
            work_type="CORRECTIVE", title="Orden cruzada", created_at=DAY,
        )
        crossed_area = CommonArea.objects.create(
            condominium=cls.a, sector=cls.sector_b, name="Área cruzada"
        )
        for area, resident, status, offset in (
            (cls.area_a, cls.resident_a, "APPROVED", 0),
            (cls.area_b, resident_b, "PENDING", 0),
            (cls.area_a, resident_b, "REJECTED", 3),
            (crossed_area, cls.resident_a, "APPROVED", 5),
        ):
            start = DAY + timedelta(hours=offset)
            Reservation.objects.create(
                common_area=area, resident=resident, status=status, start_at=start,
                end_at=start + timedelta(hours=1), created_at=DAY - timedelta(days=1),
            )

    @classmethod
    def member(cls, label, tenant, role):
        email = f"{label}@example.test"
        person = Person.objects.create(first_name=label, last_name="CU30", document_number=label)
        user = get_user_model().objects.create_user(
            email=email, password="LocalTest123!", person=person, role=role, is_approved=True,
        )
        TenantMembership.objects.create(user=user, condominium=tenant, role=role, is_default=True)
        return user

    def get_dashboard(self, user, *, tenant=None, **dates):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
        headers = {"HTTP_X_TENANT_ID": str(tenant.pk)} if tenant else {}
        return self.client.get(reverse("cu30-dashboard"), {
            "date_from": "2026-11-22", "date_to": "2026-11-22", **dates,
        }, **headers)

    def test_admin_a_only_counts_consistent_records_and_inclusive_local_day(self):
        response = self.get_dashboard(self.admin_a)
        self.assertEqual(response.status_code, 200, response.data)
        body = response.data
        self.assertEqual(body["context"]["id"], self.a.pk)
        self.assertEqual([body["security"][key] for key in ("total", "entries", "exits", "denied")], [2, 1, 0, 1])
        self.assertEqual(sum(row["count"] for row in body["security"]["by_result"]), 2)
        self.assertEqual(body["security"]["daily"][0]["count"], 2)
        self.assertEqual(body["incidents"]["total"], 1)
        self.assertEqual(body["incidents"]["pending"], 1)
        self.assertEqual(body["incidents"]["by_priority"][0]["count"], 1)
        self.assertEqual(body["maintenance"]["total"], 2)
        self.assertEqual(body["maintenance"]["overdue"], 1)
        self.assertEqual(body["reservations"]["approved"], 1)
        self.assertEqual(body["reservations"]["by_area"], [{"key": str(self.area_a.pk), "label": self.area_a.name, "count": 1}])

    def test_admin_b_counts_only_tenant_b(self):
        response = self.get_dashboard(self.admin_b)
        self.assertEqual(response.status_code, 200)
        body = response.data
        self.assertEqual(body["context"]["id"], self.b.pk)
        self.assertEqual(body["security"]["total"], 1)
        self.assertEqual(body["security"]["exits"], 1)
        self.assertEqual(body["incidents"]["resolved"], 1)
        self.assertEqual(body["maintenance"]["completed"], 1)
        self.assertEqual(body["reservations"]["pending"], 1)

    def test_foreign_header_and_query_are_denied(self):
        for response in (
            self.get_dashboard(self.admin_a, tenant=self.b),
            self.get_dashboard(self.admin_a, condominium_id=str(self.b.pk)),
        ):
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("security", response.json())

    def test_platform_requires_explicit_authorized_tenant(self):
        self.assertEqual(self.get_dashboard(self.platform).status_code, 403)
        response = self.get_dashboard(self.platform, tenant=self.b)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["context"]["id"], self.b.pk)
        self.assertEqual(response.data["security"]["total"], 1)

    def test_non_admin_and_inactive_membership_are_denied(self):
        self.assertEqual(self.client.get(reverse("cu30-dashboard")).status_code, 401)
        self.assertEqual(self.get_dashboard(self.resident_user).status_code, 403)
        TenantMembership.objects.filter(user=self.admin_a).update(is_active=False)
        self.assertEqual(self.get_dashboard(self.admin_a).status_code, 403)

    def test_empty_tenant_has_zero_and_invalid_period_is_rejected(self):
        response = self.get_dashboard(self.admin_empty)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["has_data"])
        for section in ("security", "incidents", "maintenance", "reservations"):
            self.assertEqual(response.data[section]["total"], 0)
            self.assertEqual(response.data[section]["daily"][0]["count"], 0)
        self.assertEqual(self.get_dashboard(self.admin_a, date_to="2026-11-21").status_code, 400)
        self.assertEqual(self.get_dashboard(self.admin_a, date_from="2024-11-22").status_code, 400)
        self.assertEqual(self.get_dashboard(self.admin_a, date_from="2026-02-30").status_code, 400)

    def test_status_counts_reflect_current_state_of_same_creation_cohort(self):
        Incident.objects.filter(condominium=self.a, public_code="CU30-IA").update(status="RESOLVED")
        WorkOrder.objects.filter(condominium=self.a, public_code="CU30-WA").update(status="COMPLETED")
        body = self.get_dashboard(self.admin_a).data
        self.assertEqual((body["incidents"]["total"], body["incidents"]["resolved"]), (1, 1))
        self.assertEqual((body["maintenance"]["total"], body["maintenance"]["overdue"]), (2, 0))
