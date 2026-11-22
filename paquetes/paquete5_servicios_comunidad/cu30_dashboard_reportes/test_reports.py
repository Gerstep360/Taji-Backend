import csv
from io import BytesIO, StringIO
from unittest.mock import patch

from django.urls import reverse
from openpyxl import load_workbook
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Role, SystemPermission
from auditlog.models import AuditEvent
from community.models import Agreement, Assembly
from incidents.models import Incident
from tenancy.models import TenantMembership

from . import tests as dashboard_tests
from .report_catalog import SOURCES

DAY = dashboard_tests.DAY
DATES = {"date_from": "2026-11-22", "date_to": "2026-11-22"}


class TenantReportTests(dashboard_tests.DashboardTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        assembly_a = Assembly.objects.create(condominium=cls.a, title="Asamblea A", scheduled_at=DAY)
        assembly_b = Assembly.objects.create(condominium=cls.b, title="Asamblea B", scheduled_at=DAY)
        Agreement.objects.create(assembly=assembly_a, title="Acuerdo A", created_at=DAY)
        Agreement.objects.create(assembly=assembly_b, title="Acuerdo B", created_at=DAY)
        Agreement.objects.create(
            assembly=assembly_a, title="Acuerdo cruzado", responsible_user=cls.admin_b, created_at=DAY,
        )
        for tenant, action in ((cls.a, "fixture.a"), (cls.b, "fixture.b"), (None, "fixture.global")):
            AuditEvent.objects.create(condominium=tenant, action_code=action, resource_type="fixture", occurred_at=DAY)

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")

    def call_report(self, action, source="incidents", *, tenant=None, **payload):
        url = reverse(f"cu30-reports-{action}")
        options = {"HTTP_X_TENANT_ID": str(tenant.pk)} if tenant else {}
        if action == "catalog":
            return self.client.get(url, **options)
        return self.client.post(url, {"source": source, **DATES, **payload}, format="json", **options)

    def test_six_sources_are_scoped_and_match_dashboard(self):
        for user, tenant, totals in (
            (self.admin_a, self.a, [2, 1, 2, 1, 1, 1]),
            (self.admin_b, self.b, [1, 1, 1, 1, 1, 1]),
        ):
            with self.subTest(tenant=tenant.pk):
                self.authenticate(user)
                catalog = self.call_report("catalog")
                self.assertEqual(catalog.status_code, 200)
                self.assertEqual(catalog.data["context"]["id"], tenant.pk)
                self.assertEqual({row["key"] for row in catalog.data["sources"]}, set(SOURCES))
                dashboard = self.get_dashboard(user).data
                for index, (source, expected) in enumerate(zip(SOURCES, totals)):
                    response = self.call_report("preview", source)
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["pagination"]["total"], expected, source)
                    self.assertNotIn("cruzado", str(response.data["rows"]))
                    export = self.call_report("export", source, format="csv")
                    self.assertEqual(export.status_code, 200)
                    exported = list(csv.reader(StringIO(export.content.decode("utf-8-sig"))))
                    self.assertEqual(exported[1:], response.data["rows"])
                    if index < 4:
                        section = ("security", "incidents", "maintenance", "reservations")[index]
                        self.assertEqual(expected, dashboard[section]["total"])
                    if source == "audit_events":
                        self.assertIn(f"fixture.{tenant.slug[-1]}", str(response.data["rows"]))

    def test_forbidden_tenant_and_platform_rules_apply_to_all_operations(self):
        for action in ("catalog", "preview", "export"):
            payload = {"format": "csv"} if action == "export" else {}
            self.authenticate(self.admin_a)
            self.assertEqual(self.call_report(action, tenant=self.b, **payload).status_code, 403)
            self.authenticate(self.resident_user)
            self.assertEqual(self.call_report(action, **payload).status_code, 403)
            self.authenticate(self.platform)
            self.assertEqual(self.call_report(action, **payload).status_code, 403)
            response = self.call_report(action, "agreements", tenant=self.b, **payload)
            self.assertEqual(response.status_code, 200)
            self.assertIn("private, no-store", response["Cache-Control"])
            if action == "preview":
                self.assertIn("Acuerdo B", str(response.data["rows"]))
                self.assertNotIn("Acuerdo A", str(response.data["rows"]))
            if action == "export":
                self.assertIn(b"Acuerdo B", response.content)
                self.assertNotIn(b"Acuerdo A", response.content)

    def test_catalog_and_both_data_endpoints_obey_membership_permissions(self):
        limited = Role.objects.create(name="CU30 limitado", slug="admin")
        limited.permissions.add(*SystemPermission.objects.filter(code__in=("view_reports", "manage_incidents")))
        TenantMembership.objects.filter(user=self.admin_a).update(role=limited)
        self.authenticate(self.admin_a)
        catalog = self.call_report("catalog")
        self.assertEqual([entry["key"] for entry in catalog.data["sources"]], ["incidents"])
        for key in ("access_events", "audit_events"):
            self.assertEqual(self.call_report("preview", key).status_code, 403)
            self.assertEqual(self.call_report("export", key, format="csv").status_code, 403)
        limited.permissions.add(SystemPermission.objects.get(code="manage_roles"))
        self.assertIn("audit_events", [entry["key"] for entry in self.call_report("catalog").data["sources"]])

    def test_invalid_filters_and_schema_are_rejected(self):
        self.authenticate(self.admin_a)
        invalid = (
            {"source": "unknown"},
            {"columns": ["password"]},
            {"columns": ["title", "title"]},
            {"filters": [{"field": "condominium_id", "operator": "eq", "value": str(self.b.pk)}]},
            {"filters": [{"field": "status", "operator": "contains", "value": "REPORTED"}]},
            {"filters": [{"field": "status", "operator": "eq", "value": "UNKNOWN"}]},
            {"filters": [{"field": "created_at", "operator": "eq", "value": "2026-02-30"}]},
            {"filters": [{"field": "title", "operator": "eq", "value": "x", "extra": True}]},
            {"ordering": [{"field": "title", "direction": "unknown"}]},
            {"ordering": [{"field": "reporter_user__email", "direction": "asc"}]},
            {"date_from": "2026-11-23"}, {"date_from": "2024-01-01"}, {"date_from": "2026-1-1"}, {"page_size": 101},
            {"page": 0}, {"condominium_id": str(self.b.pk)},
        )
        for criteria in invalid:
            with self.subTest(criteria=criteria):
                self.assertEqual(self.call_report("preview", **criteria).status_code, 400)
                self.assertEqual(self.call_report("export", format="csv", **criteria).status_code, 400)
        self.assertEqual(self.call_report("export", format="xml").status_code, 400)

    def test_date_filters_pagination_and_export_share_stable_order(self):
        self.authenticate(self.admin_a)
        filters = [{"field": "occurred_at", "operator": "eq", "value": DATES["date_from"]}]
        criteria = {
            "filters": filters, "columns": ["occurred_at", "event_type"],
            "ordering": [{"field": "occurred_at", "direction": "asc"}], "page_size": 1,
        }
        first = self.call_report("preview", "access_events", page=1, **criteria).data
        second = self.call_report("preview", "access_events", page=2, **criteria).data
        self.assertEqual(first["pagination"]["total"], 2)
        self.assertNotEqual(first["rows"], second["rows"])
        self.assertEqual(first["rows"][0][0], "22/11/2026 00:00")
        response = self.call_report("export", "access_events", page=2, format="csv", **criteria)
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[1:], first["rows"] + second["rows"])
        self.assertEqual(self.call_report("preview", "access_events", page=1, **criteria).data["rows"], first["rows"])

    def test_formats_neutralize_formulas_and_markup(self):
        Incident.objects.filter(condominium=self.a, public_code="CU30-IA").update(title=" =1+2")
        self.authenticate(self.admin_a)
        export = self.call_report("export", columns=["title"], format="csv")
        self.assertEqual(list(csv.reader(StringIO(export.content.decode("utf-8-sig"))))[1], ["' =1+2"])
        export = self.call_report("export", columns=["title"], title="=1+2", format="xlsx")
        book = load_workbook(BytesIO(export.content))
        self.assertEqual(book["Reporte"]["A2"].data_type, "s")
        self.assertEqual(book["Configuración"]["B1"].data_type, "s")

        Incident.objects.filter(condominium=self.a, public_code="CU30-IA").update(title="<script>alert(1)</script>")
        html = self.call_report("export", columns=["title"], format="html")
        self.assertIn(b"&lt;script&gt;", html.content)
        self.assertNotIn(b"<script>", html.content)
        self.assertIn("sandbox", html["Content-Security-Policy"])
        pdf = self.call_report("export", columns=["title"], title='<link href="https://example.test">x</link>', format="pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertNotIn(b"/URI", pdf.content)
        self.assertNotIn(b"/JavaScript", pdf.content)

    def test_empty_exports_and_row_limits(self):
        self.authenticate(self.admin_empty)
        response = self.call_report("preview", "reservations")
        self.assertEqual(response.data["rows"], [])
        self.assertTrue(all(response.data["can_export"].values()))
        for fmt in ("csv", "xlsx", "html", "pdf"):
            response = self.call_report("export", "reservations", format=fmt)
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'cu30-reservations.{fmt}', response["Content-Disposition"])
            self.assertTrue(response.content)
        self.authenticate(self.admin_a)
        with patch.dict("paquetes.paquete5_servicios_comunidad.cu30_dashboard_reportes.report_views.EXPORT_LIMITS", {"csv": 1}):
            preview = self.call_report("preview", "access_events")
            self.assertFalse(preview.data["can_export"]["csv"])
            self.assertEqual(self.call_report("export", "access_events", format="csv").status_code, 400)
