import json
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from accounts.models import Role, User
from condominiums.models import Condominium
from tenancy.models import TenantMembership

from .ai import AdvisorUnavailable, advise
from .models import AnalysisAttempt
from .serializers import CHECKS


class OperationsTests(APITestCase):
    base = "/api/v1/operations/"

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.other = [Condominium.objects.create(name=name, slug=slug)
                                 for name, slug in [("Demo A", "ops-a"), ("Demo B", "ops-b")]]
        for attr, role_slug, tenant in (("admin", "administrador", cls.tenant),
                                        ("other_admin", "administrador", cls.other),
                                        ("resident", "residente", cls.tenant)):
            role = Role.objects.get(slug=role_slug)
            person = User.objects.create_user(email=attr + "@ops.example", role=role, is_approved=True)
            TenantMembership.objects.create(user=person, condominium=tenant, role=role, is_default=True)
            setattr(cls, attr, person)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def record(self, kind, **overrides):
        states = {"quotes": "received", "warranties": "active", "inspections": "draft"}
        details = {
            "quotes": {"provider": "Proveedor privado", "request_code": "P-1", "amount": "561.25",
                       "currency": "BOB", "delivery_days": 3, "warranty_months": 12, "scope": "Detalle privado"},
            "warranties": {"provider": "Empresa", "reference": "GAR-7", "coverage": "Motor"},
            "inspections": {"location": "Lugar privado", "notes": "Notas privadas",
                            "checks": {key: "attention" if key == "order" else "ok" for key in CHECKS}},
        }[kind]
        return {"title": "Registro " + kind, "date": "2026-11-22", "status": states[kind],
                "details": {**details, **overrides}}

    def create(self, kind, **options):
        res = self.client.post(self.base + kind + "/", self.record(kind, **options), format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["id"]

    def analyze(self, kind, ids):
        return self.client.post(self.base + kind + "/analyze/", {"ids": ids}, format="json")

    def test_three_crud_and_filters(self):
        for kind in ("warranties", "quotes", "inspections"):
            with self.subTest(kind=kind):
                pk = self.create(kind)
                route = f"{self.base}{kind}/"
                detail = f"{route}{pk}/"
                self.assertEqual(self.client.get(detail).status_code, 200)
                self.assertEqual(self.client.get(route, {"q": kind}).data["count"], 1)
                self.assertEqual(self.client.get(route, {"status": self.record(kind)["status"]}).data["count"], 1)
                self.assertEqual(self.client.get(route, {"q": "no-existe"}).data["count"], 0)
                change = {**self.record(kind), "title": "Editado", "condominium": self.other.pk}
                self.assertEqual(self.client.put(detail, change, format="json").data["title"], "Editado")
                self.assertEqual(self.client.delete(detail).status_code, 204)
                self.assertEqual(self.client.get(detail).status_code, 404)

    def test_permission_and_isolation(self):
        pk = self.create("quotes")
        self.client.force_authenticate(self.other_admin)
        self.assertEqual(self.client.get(self.base + "quotes/").data["count"], 0)
        self.assertEqual(self.client.delete(f"{self.base}quotes/{pk}/").status_code, 404)
        self.assertEqual(self.analyze("quotes", [pk, 99999]).status_code, 400)
        self.client.force_authenticate(self.resident)
        self.assertEqual(self.client.get(self.base + "quotes/").status_code, 403)

    def test_invalid_inputs(self):
        for kind, options in [("quotes", {"amount": "-1"}), ("inspections", {"checks": {"fake": "ok"}}),
                              ("warranties", {"reference": ""})]:
            r = self.client.post(self.base + kind + "/", self.record(kind, **options), format="json")
            self.assertEqual(r.status_code, 400)
        r = self.client.put(self.base + f"quotes/{self.create('quotes')}/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    @patch("operations.views.advise", return_value={"summary": "Alternativas distintas.", "actions": ["Verificar cobertura."]})
    def test_both_ai_flows_and_minimal_inputs(self, advise_mock):
        a, b = self.create("quotes"), self.create("quotes", amount="400.00", delivery_days=10)
        foreign_currency = self.create("quotes", currency="USD")
        self.assertEqual(self.analyze("quotes", [a, foreign_currency]).status_code, 400)
        self.assertEqual(self.analyze("quotes", [a, a]).status_code, 400)
        result = self.analyze("quotes", [a, b])
        self.assertEqual(result.data["facts"]["lowest_amount"], "400.00")
        self.assertEqual(result.data["facts"]["fastest_delivery_days"], 3)
        self.assertEqual(result.data["ids"], [a, b])
        self.assertTrue(result.data["suggestion"]["summary"])
        self.assertNotIn("privado", repr(advise_mock.call_args))
        inspection = self.create("inspections")
        self.assertEqual(self.analyze("inspections", [inspection]).data["facts"]["checks"]["Orden y limpieza"], "attention")
        self.assertNotIn("privad", repr(advise_mock.call_args))
        self.assertEqual(AnalysisAttempt.objects.count(), 2)

    @patch("operations.views.advise", side_effect=AdvisorUnavailable)
    def test_provider_unavailable_and_rate_limit(self, advise_mock):
        pk = self.create("inspections")
        for _ in range(4):
            result = self.analyze("inspections", [pk])
            self.assertEqual(result.status_code, 200)
            self.assertIsNone(result.data["suggestion"])
            self.assertTrue(result.data["facts"])
        self.assertEqual(self.analyze("inspections", [pk]).status_code, 429)
        self.assertEqual(advise_mock.call_count, 4)


@override_settings(NVIDIA={"BASE_URL": "https://integrate.api.nvidia.com/v1", "MODEL": "demo", "API_KEY": "test",
                          "ENABLED": True, "TIMEOUT_SECONDS": 9})
class ProviderTests(SimpleTestCase):
    def test_validation_and_wire_contract(self):
        def provider(request):
            self.assertEqual(request.url.host, "integrate.api.nvidia.com")
            self.assertEqual(json.loads(request.content)["response_format"]["type"], "json_object")
            choice = {"finish_reason": "stop", "message": {"content": '{"summary":"Revisión","actions":["Validar alcance"]}'}}
            return httpx.Response(200, json={"choices": [choice]})
        self.assertEqual(advise("quotes", {"options": []}, transport=httpx.MockTransport(provider))["actions"],
                         ["Validar alcance"])

    def test_malformed_output_is_rejected(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"summary":"x","actions":42}'}}]}
        with self.assertRaises(AdvisorUnavailable):
            advise("inspections", {}, transport=httpx.MockTransport(lambda req: httpx.Response(200, json=response)))
