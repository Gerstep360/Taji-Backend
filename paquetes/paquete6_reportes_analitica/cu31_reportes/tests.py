from datetime import datetime, timedelta, timezone as dt_timezone
from io import BytesIO

from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APITestCase

from accounts.models import Person, Role, User
from condominiums.models import Condominium, Resident, Sector, Staff, Unit
from incidents.models import Incident, IncidentCategory, PriorityLevel
from security.models import SecurityShift, ShiftHandover, ShiftLogEntry
from tenancy.context import TenantContext
from tenancy.models import TenantMembership


class Cu31ReportesVoiceTests(APITestCase):
    def setUp(self):
        TenantContext.clear()
        self.addCleanup(TenantContext.clear)

        self.condo_a = Condominium.objects.create(name="Condominio Los Pinos", slug="los-pinos")
        self.condo_b = Condominium.objects.create(name="Condominio El Prado", slug="el-prado")

        self.admin_role, _ = Role.objects.get_or_create(slug="administrador", defaults={"name": "Administrador"})
        self.operator_role, _ = Role.objects.get_or_create(slug="operador", defaults={"name": "Operador"})
        self.resident_role, _ = Role.objects.get_or_create(slug="residente", defaults={"name": "Residente"})

        self.admin_user = User.objects.create_user(
            email="admin_cu31@taji.test", password="TestPassword123!", role=self.admin_role
        )
        self.membership_a = TenantMembership.objects.create(
            user=self.admin_user, condominium=self.condo_a, role=self.admin_role, is_default=True
        )

        self.client.force_authenticate(self.admin_user)

        # Reutilizar o crear categorías y prioridades existentes
        self.cat_mant = IncidentCategory.objects.filter(name="Mantenimiento").first()
        if not self.cat_mant:
            self.cat_mant = IncidentCategory.objects.first()
        if not self.cat_mant:
            self.cat_mant = IncidentCategory.objects.create(code="MANT_TEST", name="Mantenimiento Test")

        self.prio_alta = PriorityLevel.objects.filter(name__icontains="alta").first()
        if not self.prio_alta:
            self.prio_alta = PriorityLevel.objects.first()
        if not self.prio_alta:
            self.prio_alta = PriorityLevel.objects.create(code="ALTA_TEST", name="Alta", rank=1)

        self.prio_baja = PriorityLevel.objects.filter(name__icontains="baja").first()
        if not self.prio_baja:
            self.prio_baja = PriorityLevel.objects.last()
        if not self.prio_baja or self.prio_baja.pk == self.prio_alta.pk:
            self.prio_baja = PriorityLevel.objects.create(code="BAJA_TEST", name="Baja", rank=5)

        # Crear incidencias para Condo A
        self.inc_a1 = Incident.objects.create(
            condominium=self.condo_a,
            public_code="INC-A-001",
            title="Fuga de agua en pasillo piso 3",
            description="Tubería rota goteando",
            category=self.cat_mant,
            priority=self.prio_alta,
            status=Incident.Status.REPORTED,
        )
        self.inc_a2 = Incident.objects.create(
            condominium=self.condo_a,
            public_code="INC-A-002",
            title="Luz quemada en lobby",
            description="Foco LED parpadea",
            category=self.cat_mant,
            priority=self.prio_baja,
            status=Incident.Status.RESOLVED,
        )

        # Incidencia para Condo B (para probar aislamiento multi-tenant)
        self.inc_b1 = Incident.objects.create(
            condominium=self.condo_b,
            public_code="INC-B-001",
            title="Puerta de garage trabada",
            description="Portón atascado",
            category=self.cat_mant,
            priority=self.prio_alta,
            status=Incident.Status.REPORTED,
        )

        # Datos adicionales de personal y residentes
        for idx, condo in enumerate((self.condo_a, self.condo_b)):
            staff_p = Person.objects.create(
                first_name=f"Guardia_{idx}", last_name="Seguridad", document_number=f"DOC{idx}"
            )
            staff = Staff.objects.create(
                condominium=condo, staff_type="SECURITY", status="ACTIVE", person=staff_p, employee_code=f"G0{idx}"
            )

            res_p = Person.objects.create(
                first_name=f"Vecino_{idx}", last_name="Perez", document_number=f"VEC{idx}"
            )
            Resident.objects.create(condominium=condo, person=res_p, status="ACTIVE")

            sec = Sector.objects.create(condominium=condo, code=f"SEC_{idx}", name=f"Torre {idx}")
            Unit.objects.create(sector=sec, code=f"DEP-10{idx}", unit_type="APARTMENT", status="OCCUPIED")

            shift_time = timezone.now()
            s_out = SecurityShift.objects.create(
                condominium=condo,
                guard_staff=staff,
                scheduled_start=shift_time,
                scheduled_end=shift_time + timedelta(hours=8),
                status="CLOSED",
            )
            s_in = SecurityShift.objects.create(
                condominium=condo,
                guard_staff=staff,
                scheduled_start=shift_time + timedelta(hours=8),
                scheduled_end=shift_time + timedelta(hours=16),
                status="OPEN",
            )
            ShiftLogEntry.objects.create(
                shift=s_out,
                title=f"Novedad {condo.name}",
                description="Ronda perimetral sin novedad",
                severity="HIGH" if idx == 0 else "LOW",
                entry_type="OBSERVATION",
                occurred_at=shift_time,
            )
            ShiftHandover.objects.create(
                outgoing_shift=s_out,
                incoming_shift=s_in,
                summary=f"Relevo completo {condo.name}",
                status="ACCEPTED",
            )

    def test_catalog_access_and_structure(self):
        """Verifica que el catálogo de CU31 devuelva todas las fuentes, comandos de voz y formatos."""
        url = reverse("cu31-reports-catalog")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["cu"], "CU31")
        self.assertTrue(data["voice_enabled"])
        self.assertIn("voice_suggestions", data)
        self.assertGreaterEqual(len(data["voice_suggestions"]), 3)
        self.assertIn("xlsx", data["formats"])
        self.assertIn("html", data["formats"])
        self.assertIn("csv", data["formats"])

        source_keys = [s["key"] for s in data["sources"]]
        self.assertIn("incidents", source_keys)
        self.assertIn("residents", source_keys)
        self.assertIn("staff", source_keys)
        self.assertIn("units", source_keys)
        self.assertIn("shifts", source_keys)
        self.assertIn("logs", source_keys)
        self.assertIn("handovers", source_keys)

    def test_unauthorized_user_denied(self):
        """Usuarios con rol no autorizado (ej. residente ordinario) reciben 403."""
        resident_user = User.objects.create_user(
            email="vecino_simple@taji.test", password="TestPassword123!", role=self.resident_role
        )
        TenantMembership.objects.create(
            user=resident_user, condominium=self.condo_a, role=self.resident_role, is_default=True
        )
        self.client.force_authenticate(resident_user)

        response = self.client.get(reverse("cu31-reports-catalog"))
        self.assertEqual(response.status_code, 403)

    def test_multitenant_isolation(self):
        """Garantiza que un reporte ejecutado en Condominio A no liste datos del Condominio B."""
        url = reverse("cu31-reports-preview")
        payload = {
            "source": "incidents",
            "columns": ["public_code", "title", "status"],
            "filters": [],
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        returned_codes = [r[0] for r in data["rows"]]
        self.assertIn("INC-A-001", returned_codes)
        self.assertIn("INC-A-002", returned_codes)
        self.assertNotIn("INC-B-001", returned_codes)

    def test_preview_incidents_filtering(self):
        """Prueba filtros por estado en reporte de incidencias."""
        url = reverse("cu31-reports-preview")
        payload = {
            "source": "incidents",
            "columns": ["public_code", "title", "status"],
            "filters": [{"field": "status", "operator": "eq", "value": "REPORTED"}],
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["pagination"]["total"], 1)
        self.assertEqual(data["rows"][0][0], "INC-A-001")

    def test_voice_query_incidents_pending(self):
        """CU31 - Tarea 2: Consulta por comando de voz de incidencias pendientes."""
        url = reverse("cu31-reports-voice-query")
        payload = {
            "voice_text": "reporte de incidencias pendientes de esta semana",
            "auto_narrate": True,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["understood_intent"]["source"], "incidents")
        self.assertIn("spoken_summary", data)
        self.assertIn("speech_payload", data)
        self.assertTrue(data["speech_payload"]["enabled"])

        # Verifica que la consulta ejecutada devolvió solo la pendiente
        preview = data["report_preview"]
        self.assertEqual(preview["pagination"]["total"], 1)
        self.assertEqual(preview["rows"][0][0], "INC-A-001")

    def test_voice_request_can_be_reused_for_preview_and_export(self):
        response = self.client.post(
            reverse("cu31-reports-voice-query"),
            {"voice_text": "incidencias pendientes", "auto_narrate": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        query = data["report_request"]
        self.assertNotIn("format", query)
        self.assertNotIn("raw_text", query)
        preview = self.client.post(reverse("cu31-reports-preview"), query, format="json")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["rows"], data["report_preview"]["rows"])
        self.assertEqual(preview.json()["pagination"], data["report_preview"]["pagination"])
        export = self.client.post(
            reverse("cu31-reports-export"), {**query, "format": "csv"}, format="json"
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn("INC-A-001", export.content.decode("utf-8"))
        self.assertNotIn("INC-B-001", export.content.decode("utf-8"))

    def test_voice_query_residents_excel(self):
        """CU31 - Tarea 2: Comando de voz solicitando residentes en formato Excel."""
        url = reverse("cu31-reports-voice-query")
        payload = {
            "voice_text": "mostrar residentes activos en formato excel",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["understood_intent"]["source"], "residents")
        self.assertEqual(data["understood_intent"]["detected_format"], "xlsx")
        self.assertIn("Residente", data["spoken_summary"])

    def test_voice_query_logs_high_severity(self):
        """CU31 - Tarea 2: Comando de voz para novedades críticas de bitácora."""
        url = reverse("cu31-reports-voice-query")
        payload = {
            "voice_text": "novedades de seguridad de alta prioridad",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["understood_intent"]["source"], "logs")
        preview = data["report_preview"]
        self.assertEqual(preview["pagination"]["total"], 1)

    def test_voice_narrate_endpoint(self):
        """CU31 - Tarea 2: Endpoint de retroalimentación de voz."""
        url = reverse("cu31-reports-voice-narrate")
        payload = {
            "source": "incidents",
            "total_count": 3,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("spoken_summary", data)
        self.assertIn("3 registros", data["spoken_summary"])
        self.assertEqual(data["speech_payload"]["lang"], "es-ES")

    def test_export_xlsx(self):
        """CU31 - Tarea 1: Exportación en formato binario XLSX Excel."""
        url = reverse("cu31-reports-export")
        payload = {
            "source": "incidents",
            "columns": ["public_code", "title", "status"],
            "format": "xlsx",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        wb = load_workbook(filename=BytesIO(response.content))
        self.assertIn("Reporte", wb.sheetnames)
        self.assertIn("Configuración", wb.sheetnames)
        sheet = wb["Reporte"]
        # Fila 1 encabezados, filas siguientes datos
        self.assertEqual(sheet.cell(row=1, column=1).value, "Código")
        self.assertEqual(sheet.cell(row=1, column=2).value, "Título")

    def test_export_html(self):
        """CU31 - Tarea 1: Exportación en formato HTML para impresión segura."""
        url = reverse("cu31-reports-export")
        payload = {
            "source": "incidents",
            "columns": ["public_code", "title", "status"],
            "format": "html",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        html_content = response.content.decode("utf-8")
        self.assertIn("<!doctype html>", html_content)
        self.assertIn("INC-A-001", html_content)

    def test_export_csv(self):
        """CU31 - Tarea 1: Exportación en formato CSV."""
        url = reverse("cu31-reports-export")
        payload = {
            "source": "incidents",
            "columns": ["public_code", "title", "status"],
            "format": "csv",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        csv_content = response.content.decode("utf-8")
        self.assertIn("INC-A-001", csv_content)
