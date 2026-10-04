"""Pruebas unitarias e integrales para CU13: Turnos del personal de seguridad."""

from datetime import datetime, timedelta
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from auditlog.models import AuditEvent
from condominiums.models import Condominium, Staff
from security.models import SecurityShift


class CU13SecurityShiftTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. Permisos del sistema
        cls.perm_manage_shifts, _ = SystemPermission.objects.get_or_create(
            code="manage_security_shifts", defaults={"name": "Gestionar turnos", "module": "security"}
        )
        cls.perm_operate_shifts, _ = SystemPermission.objects.get_or_create(
            code="operate_security_shifts", defaults={"name": "Operar turnos", "module": "security"}
        )

        # 2. Roles
        cls.role_admin, _ = Role.objects.get_or_create(slug="administrador", defaults={"name": "Administrador"})
        cls.role_admin.permissions.add(cls.perm_manage_shifts)

        cls.role_security, _ = Role.objects.get_or_create(slug="seguridad", defaults={"name": "Seguridad"})
        cls.role_security.permissions.add(cls.perm_operate_shifts)

        cls.role_resident, _ = Role.objects.get_or_create(slug="residente", defaults={"name": "Residente"})

        # 3. Condominios
        cls.condo1 = Condominium.objects.create(name="Condominio El Bosque")
        cls.condo2 = Condominium.objects.create(name="Condominio Las Flores")

        # 4. Personal de Seguridad 1
        cls.person_guard1 = Person.objects.create(
            first_name="Juan",
            last_name="Pérez",
            document_type=Person.DocumentType.CI,
            document_number="1234567",
        )
        cls.user_guard1 = User.objects.create_user(
            email="juan.guard1@taji.test",
            password="Password123!",
            person=cls.person_guard1,
            role=cls.role_security,
            is_approved=True,
        )
        cls.staff_guard1 = Staff.objects.create(
            person=cls.person_guard1,
            employee_code="SEC-001",
            staff_type=Staff.Type.SECURITY,
            status=Staff.Status.ACTIVE,
        )

        # 5. Personal de Seguridad 2
        cls.person_guard2 = Person.objects.create(
            first_name="Mario",
            last_name="Gómez",
            document_type=Person.DocumentType.CI,
            document_number="7654321",
        )
        cls.user_guard2 = User.objects.create_user(
            email="mario.guard2@taji.test",
            password="Password123!",
            person=cls.person_guard2,
            role=cls.role_security,
            is_approved=True,
        )
        cls.staff_guard2 = Staff.objects.create(
            person=cls.person_guard2,
            employee_code="SEC-002",
            staff_type=Staff.Type.SECURITY,
            status=Staff.Status.ACTIVE,
        )

        # 6. Personal de Mantenimiento (No es Seguridad)
        cls.person_maint = Person.objects.create(
            first_name="Pedro",
            last_name="Torres",
            document_type=Person.DocumentType.CI,
            document_number="5554443",
        )
        cls.staff_maint = Staff.objects.create(
            person=cls.person_maint,
            employee_code="MNT-001",
            staff_type=Staff.Type.MAINTENANCE,
            status=Staff.Status.ACTIVE,
        )

        # 7. Administrador
        cls.person_admin = Person.objects.create(
            first_name="Ana",
            last_name="Administradora",
            document_type=Person.DocumentType.CI,
            document_number="9998887",
        )
        cls.user_admin = User.objects.create_user(
            email="admin@taji.test",
            password="Password123!",
            person=cls.person_admin,
            role=cls.role_admin,
            is_approved=True,
        )

        # 8. Residente (Sin permisos)
        cls.person_resident = Person.objects.create(
            first_name="Roberto",
            last_name="Residente",
            document_type=Person.DocumentType.CI,
            document_number="1112223",
        )
        cls.user_resident = User.objects.create_user(
            email="residente@taji.test",
            password="Password123!",
            person=cls.person_resident,
            role=cls.role_resident,
            is_approved=True,
        )

    def test_01_admin_creates_valid_shift(self):
        """1. Administrador crea un turno válido para personal de seguridad."""
        self.client.force_authenticate(user=self.user_admin)
        now = timezone.now()
        start = now + timedelta(days=1, hours=8)
        end = start + timedelta(hours=8)

        data = {
            "guard_staff": self.staff_guard1.id,
            "condominium": self.condo1.id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
            "observation": "Turno mañana principal",
        }
        url = reverse("turnos-seguridad-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["guard_staff"], self.staff_guard1.id)
        self.assertEqual(response.data["status"], SecurityShift.Status.SCHEDULED)

    def test_02_reject_non_security_staff(self):
        """2. Rechazo de personal que no pertenece al área SEGURIDAD."""
        self.client.force_authenticate(user=self.user_admin)
        now = timezone.now()
        start = now + timedelta(days=1, hours=8)
        end = start + timedelta(hours=8)

        data = {
            "guard_staff": self.staff_maint.id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
        }
        url = reverse("turnos-seguridad-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("guard_staff", response.data["error"]["fields"])

    def test_03_reject_end_time_before_or_equal_start_time(self):
        """3. Rechazo de hora final <= hora inicio."""
        self.client.force_authenticate(user=self.user_admin)
        now = timezone.now()
        start = now + timedelta(days=1, hours=16)
        end = now + timedelta(days=1, hours=10)  # Menor que inicio

        data = {
            "guard_staff": self.staff_guard1.id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
        }
        url = reverse("turnos-seguridad-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("scheduled_end", response.data["error"]["fields"])

    def test_04_reject_overlapping_shift(self):
        """4. Rechazo de solapamiento de horarios para un mismo guardia."""
        now = timezone.now()
        start1 = now + timedelta(days=2, hours=8)
        end1 = now + timedelta(days=2, hours=16)

        # Crear turno previo 08:00 - 16:00
        SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            condominium=self.condo1,
            scheduled_start=start1,
            scheduled_end=end1,
            status=SecurityShift.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.user_admin)
        # Intentar crear turno 14:00 - 20:00 (solapado)
        start2 = now + timedelta(days=2, hours=14)
        end2 = now + timedelta(days=2, hours=20)

        data = {
            "guard_staff": self.staff_guard1.id,
            "scheduled_start": start2.isoformat(),
            "scheduled_end": end2.isoformat(),
        }
        url = reverse("turnos-seguridad-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "bad_request")

    def test_05_allow_consecutive_shifts(self):
        """5. Permitir horarios consecutivos exactos sin solapamiento (ej: 08:00-16:00 y 16:00-22:00)."""
        now = timezone.now()
        start1 = now + timedelta(days=3, hours=8)
        end1 = now + timedelta(days=3, hours=16)

        SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            condominium=self.condo1,
            scheduled_start=start1,
            scheduled_end=end1,
            status=SecurityShift.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.user_admin)
        # Turno consecutivo exacto: 16:00 - 22:00
        start2 = end1
        end2 = start2 + timedelta(hours=6)

        data = {
            "guard_staff": self.staff_guard1.id,
            "scheduled_start": start2.isoformat(),
            "scheduled_end": end2.isoformat(),
        }
        url = reverse("turnos-seguridad-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_06_admin_list_all_shifts(self):
        """6. Listado administrativo global de turnos."""
        now = timezone.now()
        SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )
        SecurityShift.objects.create(
            guard_staff=self.staff_guard2,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )

        self.client.force_authenticate(user=self.user_admin)
        url = reverse("turnos-seguridad-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertGreaterEqual(len(results), 2)

    def test_07_guard_list_own_shifts(self):
        """7. Listado propio del guardia (solo ve sus turnos asignados)."""
        now = timezone.now()
        shift1 = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )
        SecurityShift.objects.create(
            guard_staff=self.staff_guard2,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], shift1.id)

    def test_08_shift_detail(self):
        """8. Detalle del turno."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-detail", args=[shift.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], shift.id)

    def test_09_edit_scheduled_shift(self):
        """9. Edición de turno programado por parte del administrador."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
            observation="Observación inicial",
        )

        self.client.force_authenticate(user=self.user_admin)
        url = reverse("turnos-seguridad-detail", args=[shift.id])
        data = {"observation": "Observación modificada"}
        response = self.client.patch(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        shift.refresh_from_db()
        self.assertEqual(shift.observation, "Observación modificada")

    def test_10_cancel_shift(self):
        """10. Cancelar turno programado (Administrador)."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )

        self.client.force_authenticate(user=self.user_admin)
        url = reverse("turnos-seguridad-cancelar", args=[shift.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        shift.refresh_from_db()
        self.assertEqual(shift.status, SecurityShift.Status.CANCELLED)

    def test_11_start_shift_successfully(self):
        """11. Iniciar turno correctamente por el guardia asignado."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now - timedelta(minutes=5),
            scheduled_end=now + timedelta(hours=8),
            status=SecurityShift.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-iniciar", args=[shift.id])
        response = self.client.post(url, {"notes": "Ingreso a garita principal"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        shift.refresh_from_db()
        self.assertEqual(shift.status, SecurityShift.Status.OPEN)
        self.assertIsNotNone(shift.opened_at)
        self.assertEqual(shift.opening_notes, "Ingreso a garita principal")

    def test_12_prevent_start_shift_by_other_guard(self):
        """12. Impedir que un guardia inicie el turno de otro guardia."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now,
            scheduled_end=now + timedelta(hours=8),
            status=SecurityShift.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.user_guard2)  # Guardia 2 sobre turno de Guardia 1
        url = reverse("turnos-seguridad-iniciar", args=[shift.id])
        response = self.client.post(url)

        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_13_prevent_start_cancelled_shift(self):
        """13. Impedir iniciar un turno en estado CANCELADO."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now,
            scheduled_end=now + timedelta(hours=8),
            status=SecurityShift.Status.CANCELLED,
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-iniciar", args=[shift.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_14_prevent_starting_twice(self):
        """14. Impedir iniciar dos veces el mismo turno."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now - timedelta(hours=1),
            scheduled_end=now + timedelta(hours=7),
            opened_at=now - timedelta(hours=1),
            status=SecurityShift.Status.OPEN,
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-iniciar", args=[shift.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_15_close_shift_successfully(self):
        """15. Cerrar turno correctamente cambiando estado a FINALIZADO (CLOSED)."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now - timedelta(hours=8),
            scheduled_end=now,
            opened_at=now - timedelta(hours=8),
            status=SecurityShift.Status.OPEN,
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-cerrar", args=[shift.id])
        response = self.client.post(url, {"notes": "Entrega de novedades sin observaciones"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        shift.refresh_from_db()
        self.assertEqual(shift.status, SecurityShift.Status.CLOSED)
        self.assertIsNotNone(shift.closed_at)
        self.assertEqual(shift.closing_notes, "Entrega de novedades sin observaciones")

    def test_16_prevent_closing_unstarted_shift(self):
        """16. Impedir cerrar un turno no iniciado (SCHEDULED)."""
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now,
            scheduled_end=now + timedelta(hours=8),
            status=SecurityShift.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-cerrar", args=[shift.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_17_current_shift_endpoint(self):
        """17. Consulta de turno actual sin errores HTTP 500 cuando no exista turno o cuando esté activo."""
        # A) Caso sin turno activo: debe retornar 200 controlado
        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-actual")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # B) Caso con turno en curso:
        now = timezone.now()
        shift = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now - timedelta(hours=1),
            scheduled_end=now + timedelta(hours=7),
            opened_at=now - timedelta(hours=1),
            status=SecurityShift.Status.OPEN,
        )
        response_active = self.client.get(url)
        self.assertEqual(response_active.status_code, status.HTTP_200_OK)
        self.assertEqual(response_active.data["id"], shift.id)

    def test_18_upcoming_shifts_endpoint(self):
        """18. Consulta de próximos turnos programados."""
        now = timezone.now()
        shift_future = SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
            status=SecurityShift.Status.SCHEDULED,
        )

        self.client.force_authenticate(user=self.user_guard1)
        url = reverse("turnos-seguridad-proximos")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], shift_future.id)

    def test_19_history_shifts_endpoint(self):
        """19. Consulta de historial de turnos (finalizados y cancelados) con filtros."""
        now = timezone.now()
        SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now - timedelta(days=2),
            scheduled_end=now - timedelta(days=2, hours=-8),
            status=SecurityShift.Status.CLOSED,
        )
        SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            scheduled_start=now - timedelta(days=1),
            scheduled_end=now - timedelta(days=1, hours=-8),
            status=SecurityShift.Status.CANCELLED,
        )

        self.client.force_authenticate(user=self.user_admin)
        url = reverse("turnos-seguridad-historial")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get("results", response.data)
        self.assertEqual(len(results), 2)


    def test_20_permissions_resident_denied(self):
        """20. Rechazo de acceso a usuarios sin rol/permiso de seguridad o administración (Residente -> 403)."""
        self.client.force_authenticate(user=self.user_resident)
        url = reverse("turnos-seguridad-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_21_condominium_isolation_and_filters(self):
        """21. Aislamiento y filtrado de turnos por condominio o guardia."""
        now = timezone.now()
        SecurityShift.objects.create(
            guard_staff=self.staff_guard1,
            condominium=self.condo1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )
        SecurityShift.objects.create(
            guard_staff=self.staff_guard2,
            condominium=self.condo2,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=8),
        )

        self.client.force_authenticate(user=self.user_admin)
        url = reverse("turnos-seguridad-list")
        response_condo1 = self.client.get(url, {"condominium": self.condo1.id})

        self.assertEqual(response_condo1.status_code, status.HTTP_200_OK)
        results = response_condo1.data.get("results", response_condo1.data)
        self.assertTrue(all(item["condominium"] == self.condo1.id for item in results))

    def test_22_audit_event_logging(self):
        """22. Verificación del registro de auditoría AuditEvent para operaciones sensibles."""
        self.client.force_authenticate(user=self.user_admin)
        now = timezone.now()
        data = {
            "guard_staff": self.staff_guard1.id,
            "scheduled_start": (now + timedelta(days=10)).isoformat(),
            "scheduled_end": (now + timedelta(days=10, hours=8)).isoformat(),
        }
        url = reverse("turnos-seguridad-list")
        resp_create = self.client.post(url, data, format="json")
        shift_id = resp_create.data["id"]

        audit_entry = AuditEvent.objects.filter(
            action_code="SECURITY_SHIFT_CREATED", resource_id=str(shift_id)
        ).first()

        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.resource_type, "SecurityShift")
