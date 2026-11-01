"""Tests para CU19: Consultar seguimiento e historial de incidencia (T034, T037, T038).

Cubre los siguientes casos:
- T034: Historial completo de estados de incidencia y transiciones.
- T037: Comentarios públicos e internos con control de acceso por rol.
- T038: Fechas objetivo (due_at), cálculo SLA, pendientes y vencidas.
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from condominiums.models import Condominium, Resident, Staff
from incidents.models import (
    Incident,
    IncidentAssignment,
    IncidentCategory,
    IncidentComment,
    IncidentStatusHistory,
    PriorityLevel,
)
from tenancy.models import TenantMembership


LIST_URL = "/api/v1/paquete3/incidents/"
BOARD_URL = "/api/v1/paquete3/incidents/board-summary/"


def incident_url(code, action=""):
    path = f"/api/v1/paquete3/incidents/{code}/"
    return path if not action else f"{path}{action}/"


class IncidentTrackingTestCase(APITestCase):
    """Clase base con helpers de creación de datos para CU19."""

    @classmethod
    def setUpTestData(cls):
        cls.condo = Condominium.objects.create(name="Condominio Taji Test")
        cls.other_condo = Condominium.objects.create(name="Condominio Otro")

        cls.admin_user = cls._make_user("administrador", "admin", "manage_incidents")
        cls.directiva_user = cls._make_user("directiva", "directiva", "view_important_incidents")
        cls.staff_person_user = cls._make_user("mantenimiento", "manto", None)
        cls.resident_user = cls._make_user("residente", "residente", "report_incidents")

        # Staff para el usuario de mantenimiento
        cls.staff_obj = Staff.objects.create(
            person=cls.staff_person_user.person,
            condominium=cls.condo,
            staff_type="MAINTENANCE",
            status=Staff.Status.ACTIVE,
        )

        # Residente para el usuario residente
        cls.resident_obj = Resident.objects.create(
            condominium=cls.condo,
            person=cls.resident_user.person,
            status=Resident.Status.ACTIVE,
        )

        # Membresías de tenant
        for user in (cls.admin_user, cls.directiva_user, cls.staff_person_user, cls.resident_user):
            TenantMembership.objects.create(
                user=user,
                condominium=cls.condo,
                role=user.role,
                is_default=True,
            )

        # Catalogos
        cls.priority = PriorityLevel.objects.get_or_create(
            code="HIGH",
            defaults={"name": "Alta", "rank": 3, "target_minutes": 120, "is_active": True},
        )[0]
        cls.priority_low = PriorityLevel.objects.get_or_create(
            code="LOW",
            defaults={"name": "Baja", "rank": 1, "target_minutes": 1440, "is_active": True},
        )[0]
        cls.category = IncidentCategory.objects.get_or_create(
            code="TEST_CAT",
            defaults={"name": "Categoría Test", "is_active": True},
        )[0]

    @classmethod
    def _make_user(cls, role_slug, name_prefix, permission_code):
        role, _ = Role.objects.get_or_create(
            slug=role_slug, defaults={"name": role_slug.title()}
        )
        if permission_code:
            perm, _ = SystemPermission.objects.get_or_create(
                code=permission_code, defaults={"name": permission_code}
            )
            role.permissions.add(perm)
        person = Person.objects.create(
            first_name=name_prefix.title(),
            last_name="Taji",
            document_number=f"DOC{name_prefix}",
        )
        return User.objects.create_user(
            email=f"{name_prefix}@taji.test",
            password="Test1234!",
            person=person,
            role=role,
            is_approved=True,
        )

    def _make_incident(self, reporter=None, priority=None, status=None, due_at=None, title=None):
        return Incident.objects.create(
            reporter_user=reporter or self.resident_user,
            reporter_resident=getattr(self, "resident_obj", None),
            category=self.category,
            priority=priority or self.priority,
            current_assignee_staff=self.staff_obj,
            sector=None,
            unit=None,
            title=title or "Incidencia de prueba",
            description="Descripción de prueba para test.",
            status=status or Incident.Status.REPORTED,
            due_at=due_at,
        )

    def auth(self, user=None):
        self.client.force_authenticate(user=user or self.admin_user)


# ─────────────────────────────────────────────────────────────────────────────
# T038: Propiedades is_pending, is_overdue, time_remaining_minutes
# ─────────────────────────────────────────────────────────────────────────────

class IncidentSLAPropertiesTests(IncidentTrackingTestCase):
    """T038: Propiedades de SLA calculadas directamente en el modelo Incident."""

    def test_pending_incident_is_pending(self):
        inc = self._make_incident(status=Incident.Status.REPORTED)
        self.assertTrue(inc.is_pending)
        self.assertFalse(inc.is_overdue)

    def test_resolved_incident_not_pending(self):
        inc = self._make_incident(status=Incident.Status.RESOLVED)
        self.assertFalse(inc.is_pending)

    def test_overdue_when_due_at_in_past(self):
        past = timezone.now() - timedelta(hours=1)
        inc = self._make_incident(status=Incident.Status.IN_PROGRESS, due_at=past)
        self.assertTrue(inc.is_overdue)
        self.assertGreater(inc.overdue_by_minutes, 0)

    def test_not_overdue_when_due_at_future(self):
        future = timezone.now() + timedelta(hours=2)
        inc = self._make_incident(status=Incident.Status.IN_PROGRESS, due_at=future)
        self.assertFalse(inc.is_overdue)
        self.assertIsNotNone(inc.time_remaining_minutes)

    def test_resolved_incident_not_overdue_even_if_past_due(self):
        past = timezone.now() - timedelta(hours=1)
        inc = self._make_incident(status=Incident.Status.RESOLVED, due_at=past)
        self.assertFalse(inc.is_overdue)

    def test_due_at_auto_set_from_priority(self):
        """T038: Al crear una incidencia con prioridad, due_at se calcula automáticamente."""
        inc = Incident.objects.create(
            reporter_user=self.resident_user,
            category=self.category,
            priority=self.priority,  # target_minutes=120
            title="Test due_at automático",
            description="Debe calcular due_at desde target_minutes.",
        )
        self.assertIsNotNone(inc.due_at)
        diff = inc.due_at - inc.created_at
        self.assertAlmostEqual(diff.total_seconds() / 60, 120, delta=2)

    def test_public_code_auto_generated(self):
        """El public_code se genera automáticamente en formato INC-YYYYMMDD-XXXXXX."""
        inc = Incident.objects.create(
            reporter_user=self.resident_user,
            category=self.category,
            priority=self.priority,
            title="Test código público",
            description="Para probar la generación del código.",
        )
        self.assertRegex(inc.public_code, r"^INC-\d{8}-[A-F0-9]{6}$")


# ─────────────────────────────────────────────────────────────────────────────
# T038: Endpoint de tablero y filtros de SLA
# ─────────────────────────────────────────────────────────────────────────────

class IncidentBoardFilterTests(IncidentTrackingTestCase):
    """T038: Filtros de pendientes, vencidas y tablero de incidencias."""

    def setUp(self):
        now = timezone.now()
        self.inc_pending = self._make_incident(status=Incident.Status.REPORTED, due_at=now + timedelta(hours=5))
        self.inc_overdue = self._make_incident(status=Incident.Status.IN_PROGRESS, due_at=now - timedelta(hours=2))
        self.inc_resolved = self._make_incident(status=Incident.Status.RESOLVED)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_list_all_incidents(self):
        self.auth(self.admin_user)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        count = response.data.get("count", len(response.data))
        self.assertGreaterEqual(count, 3)

    def test_filter_by_overdue(self):
        self.auth(self.admin_user)
        response = self.client.get(LIST_URL, {"sla_status": "overdue"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        codes = [r["public_code"] for r in results]
        self.assertIn(self.inc_overdue.public_code, codes)
        self.assertNotIn(self.inc_pending.public_code, codes)
        self.assertNotIn(self.inc_resolved.public_code, codes)

    def test_filter_by_pending(self):
        self.auth(self.admin_user)
        response = self.client.get(LIST_URL, {"is_pending": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        statuses = [r["status"] for r in results]
        self.assertTrue(all(s in ("REPORTED", "REVIEWED", "ASSIGNED", "IN_PROGRESS") for s in statuses))

    def test_board_summary_metrics(self):
        self.auth(self.admin_user)
        response = self.client.get(BOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn("pending_count", data)
        self.assertIn("overdue_count", data)
        self.assertIn("on_time_count", data)
        self.assertIn("resolved_count", data)
        self.assertIn("by_status", data)
        self.assertIn("by_priority", data)
        self.assertGreaterEqual(data["overdue_count"], 1)
        self.assertGreaterEqual(data["resolved_count"], 1)

    def test_resident_only_sees_own_incidents(self):
        """T038 + Paso 43-44: Residente solo ve sus propias incidencias."""
        other_person = Person.objects.create(first_name="Otro", last_name="Residente", document_number="DOC_OTRO2")
        other_resident_user = User.objects.create_user(
            email="otro_res2@taji.test",
            password="Test1234!",
            person=other_person,
            role=self.resident_user.role,
            is_approved=True,
        )
        Incident.objects.create(
            reporter_user=other_resident_user,
            category=self.category,
            priority=self.priority,
            title="Incidencia de otro residente",
            description="No debe verse por self.resident_user.",
        )
        self.auth(self.resident_user)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        for r in results:
            reporter_id = (r.get("reporter_user") or {}).get("id")
            self.assertEqual(reporter_id, self.resident_user.id)

    def test_response_includes_sla_fields(self):
        """T038: Los campos de SLA están presentes en la respuesta del listado."""
        self.auth(self.admin_user)
        response = self.client.get(LIST_URL)
        results = response.data.get("results", response.data)
        if results:
            item = results[0]
            self.assertIn("is_pending", item)
            self.assertIn("is_overdue", item)
            self.assertIn("due_at", item)
            self.assertIn("time_remaining_minutes", item)

    def test_set_target_date_with_minutes(self):
        """T038: Establecer fecha objetivo usando target_minutes."""
        inc = self._make_incident(due_at=None)
        self.auth(self.admin_user)
        response = self.client.post(
            incident_url(inc.public_code, "set-target-date"),
            {"target_minutes": 60},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        inc.refresh_from_db()
        self.assertIsNotNone(inc.due_at)

    def test_set_target_date_requires_admin(self):
        """T038: Solo administradores pueden modificar la fecha objetivo."""
        inc = self._make_incident(due_at=None)
        self.auth(self.resident_user)
        response = self.client.post(
            incident_url(inc.public_code, "set-target-date"),
            {"target_minutes": 60},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))


# ─────────────────────────────────────────────────────────────────────────────
# T034: Historial de estados
# ─────────────────────────────────────────────────────────────────────────────

class IncidentStatusHistoryTests(IncidentTrackingTestCase):
    """T034: Historial completo de estados con control de transiciones."""

    def setUp(self):
        self.incident = self._make_incident(status=Incident.Status.REPORTED)

    def test_history_endpoint_returns_list(self):
        """T034: El endpoint /history/ retorna el historial ordenado."""
        IncidentStatusHistory.objects.create(
            incident=self.incident,
            changed_by_user=self.admin_user,
            from_status=None,
            to_status=Incident.Status.REPORTED,
            comment="Incidencia registrada.",
        )
        self.auth(self.admin_user)
        response = self.client.get(incident_url(self.incident.public_code, "history"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 1)
        entry = response.data[0]
        self.assertIn("from_status", entry)
        self.assertIn("to_status", entry)
        self.assertIn("changed_at", entry)
        self.assertIn("changed_by", entry)
        self.assertIn("comment", entry)

    def test_detail_includes_status_history(self):
        """T034: El detalle de incidencia incluye el historial completo."""
        IncidentStatusHistory.objects.create(
            incident=self.incident,
            changed_by_user=self.admin_user,
            from_status=None,
            to_status=Incident.Status.REPORTED,
            comment="Primera entrada.",
        )
        self.auth(self.admin_user)
        response = self.client.get(incident_url(self.incident.public_code))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("status_history", response.data)
        self.assertIsInstance(response.data["status_history"], list)

    def test_admin_can_change_status_and_history_is_recorded(self):
        """T034: Cambio de estado genera un registro en IncidentStatusHistory."""
        self.auth(self.admin_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "change-status"),
            {"status": "IN_PROGRESS", "comment": "Iniciando revisión."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, Incident.Status.IN_PROGRESS)
        history = IncidentStatusHistory.objects.filter(incident=self.incident)
        self.assertEqual(history.count(), 1)
        h = history.first()
        self.assertEqual(h.from_status, Incident.Status.REPORTED)
        self.assertEqual(h.to_status, Incident.Status.IN_PROGRESS)
        self.assertEqual(h.comment, "Iniciando revisión.")
        self.assertEqual(h.changed_by_user, self.admin_user)

    def test_invalid_status_returns_400(self):
        """T034: Estado inválido devuelve HTTP 400."""
        self.auth(self.admin_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "change-status"),
            {"status": "INVALID_STATUS"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_same_status_returns_400(self):
        """T034: Cambiar al mismo estado devuelve HTTP 400."""
        self.auth(self.admin_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "change-status"),
            {"status": Incident.Status.REPORTED, "comment": "Igual que antes."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_can_move_to_in_progress_when_assigned(self):
        """T034: Personal asignado puede cambiar a IN_PROGRESS."""
        self.incident.status = Incident.Status.ASSIGNED
        self.incident.current_assignee_staff = self.staff_obj
        self.incident.save()
        self.auth(self.staff_person_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "change-status"),
            {"status": "IN_PROGRESS"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, Incident.Status.IN_PROGRESS)

    def test_resident_cannot_change_status_to_in_progress(self):
        """T034: Residente no puede cambiar estado a IN_PROGRESS."""
        self.auth(self.resident_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "change-status"),
            {"status": "IN_PROGRESS"},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_resolved_at_set_when_status_resolved(self):
        """T034: Al pasar a RESOLVED, se guarda resolved_at."""
        self.incident.status = Incident.Status.IN_PROGRESS
        self.incident.save()
        self.auth(self.admin_user)
        self.client.post(
            incident_url(self.incident.public_code, "change-status"),
            {"status": "RESOLVED", "comment": "Problema resuelto."},
            format="json",
        )
        self.incident.refresh_from_db()
        self.assertIsNotNone(self.incident.resolved_at)

    def test_history_list_shows_from_status_display(self):
        """T034: El historial muestra from_status legible cuando es None ('Inicio')."""
        IncidentStatusHistory.objects.create(
            incident=self.incident,
            changed_by_user=self.admin_user,
            from_status=None,
            to_status=Incident.Status.REPORTED,
            comment="",
        )
        self.auth(self.admin_user)
        response = self.client.get(incident_url(self.incident.public_code, "history"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["from_status_display"], "Inicio")


# ─────────────────────────────────────────────────────────────────────────────
# T037: Comentarios públicos e internos
# ─────────────────────────────────────────────────────────────────────────────

class IncidentCommentTests(IncidentTrackingTestCase):
    """T037: Comentarios públicos e internos con control de visibilidad por rol."""

    def setUp(self):
        self.incident = self._make_incident(status=Incident.Status.REPORTED)

    def test_admin_can_post_public_comment(self):
        self.auth(self.admin_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "comments"),
            {"body": "Comentario público del admin.", "visibility": "PUBLIC"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["visibility"], "PUBLIC")

    def test_admin_can_post_internal_comment(self):
        """T037: El administrador puede publicar comentarios internos."""
        self.auth(self.admin_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "comments"),
            {"body": "Comentario interno confidencial.", "visibility": "INTERNAL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["visibility"], "INTERNAL")

    def test_staff_can_post_internal_comment(self):
        """T037: El personal operativo puede publicar comentarios internos."""
        self.auth(self.staff_person_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "comments"),
            {"body": "Nota interna de mantenimiento.", "visibility": "INTERNAL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_resident_cannot_post_internal_comment(self):
        """T037: El residente NO puede publicar comentarios internos (403)."""
        self.auth(self.resident_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "comments"),
            {"body": "Intento interno.", "visibility": "INTERNAL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_resident_can_post_public_comment(self):
        """T037: El residente puede publicar comentarios públicos."""
        self.auth(self.resident_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "comments"),
            {"body": "Sigo esperando resolución.", "visibility": "PUBLIC"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_resident_cannot_read_internal_comments(self):
        """T037: El residente no puede consultar comentarios internos (403)."""
        IncidentComment.objects.create(
            incident=self.incident,
            author_user=self.admin_user,
            body="Nota interna.",
            visibility=IncidentComment.Visibility.INTERNAL,
        )
        self.auth(self.resident_user)
        response = self.client.get(
            incident_url(self.incident.public_code, "comments"),
            {"visibility": "INTERNAL"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_reads_both_visibility_levels(self):
        """T037: Admin ve comentarios de ambas visibilidades."""
        IncidentComment.objects.create(
            incident=self.incident,
            author_user=self.admin_user,
            body="Público.",
            visibility=IncidentComment.Visibility.PUBLIC,
        )
        IncidentComment.objects.create(
            incident=self.incident,
            author_user=self.admin_user,
            body="Interno.",
            visibility=IncidentComment.Visibility.INTERNAL,
        )
        self.auth(self.admin_user)

        # Sin filtro → ve todos
        response = self.client.get(incident_url(self.incident.public_code, "comments"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        # Filtro PUBLIC
        resp_pub = self.client.get(incident_url(self.incident.public_code, "comments"), {"visibility": "PUBLIC"})
        self.assertEqual(len(resp_pub.data), 1)
        self.assertEqual(resp_pub.data[0]["visibility"], "PUBLIC")

        # Filtro INTERNAL
        resp_int = self.client.get(incident_url(self.incident.public_code, "comments"), {"visibility": "INTERNAL"})
        self.assertEqual(len(resp_int.data), 1)
        self.assertEqual(resp_int.data[0]["visibility"], "INTERNAL")

    def test_resident_gets_only_public_on_detail(self):
        """T037: El detalle devuelto al residente no incluye comentarios internos."""
        IncidentComment.objects.create(
            incident=self.incident,
            author_user=self.admin_user,
            body="Interno oculto.",
            visibility=IncidentComment.Visibility.INTERNAL,
        )
        IncidentComment.objects.create(
            incident=self.incident,
            author_user=self.admin_user,
            body="Público visible.",
            visibility=IncidentComment.Visibility.PUBLIC,
        )
        self.auth(self.resident_user)
        response = self.client.get(incident_url(self.incident.public_code))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["internal_comments"]), 0)
        self.assertEqual(len(response.data["public_comments"]), 1)

    def test_empty_body_comment_returns_400(self):
        """T037: Comentario con cuerpo vacío devuelve HTTP 400."""
        self.auth(self.admin_user)
        response = self.client.post(
            incident_url(self.incident.public_code, "comments"),
            {"body": "  ", "visibility": "PUBLIC"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────────────────────
# Detalle completo (DetalleIncidenciaDTO)
# ─────────────────────────────────────────────────────────────────────────────

class IncidentDetailViewTests(IncidentTrackingTestCase):
    """Verificación del endpoint de detalle completo de la incidencia."""

    def setUp(self):
        self.incident = self._make_incident()

    def test_detail_fields_structure(self):
        """El detalle incluye todos los campos esperados por el DTO."""
        self.auth(self.admin_user)
        response = self.client.get(incident_url(self.incident.public_code))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        for field in (
            "id", "public_code", "title", "description", "status", "status_display",
            "category", "priority", "sector", "unit",
            "current_assignee", "reporter_user", "reporter_resident",
            "due_at", "created_at", "updated_at",
            "is_pending", "is_overdue",
            "status_history", "assignments", "public_comments", "internal_comments", "attachments",
            "can_view_internal_comments", "can_change_status", "can_modify_target_date",
        ):
            self.assertIn(field, data, f"Campo '{field}' faltante en el DTO de detalle.")

    def test_not_found_incident_returns_400(self):
        self.auth(self.admin_user)
        response = self.client.get(incident_url("INC-99999999-ZZZZZZ"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resident_cannot_view_others_incident_detail(self):
        """Residente no puede acceder al detalle de una incidencia que no es suya."""
        other_person = Person.objects.create(
            first_name="OtroR", last_name="Vecino", document_number="DOC_VEC"
        )
        other_user = User.objects.create_user(
            email="vecino@taji.test",
            password="Test1234!",
            person=other_person,
            role=self.resident_user.role,
            is_approved=True,
        )
        foreign_incident = self._make_incident(reporter=other_user)
        self.auth(self.resident_user)
        response = self.client.get(incident_url(foreign_incident.public_code))
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST))

    def test_directiva_can_see_details(self):
        self.auth(self.directiva_user)
        response = self.client.get(incident_url(self.incident.public_code))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_resident_cannot_modify_target_date(self):
        """T038: El campo can_modify_target_date es False para residentes."""
        self.auth(self.resident_user)
        response = self.client.get(incident_url(self.incident.public_code))
        if response.status_code == status.HTTP_200_OK:
            self.assertFalse(response.data.get("can_modify_target_date", True))

    def test_admin_can_modify_target_date(self):
        """T038: El campo can_modify_target_date es True para administradores."""
        self.auth(self.admin_user)
        response = self.client.get(incident_url(self.incident.public_code))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("can_modify_target_date"))
