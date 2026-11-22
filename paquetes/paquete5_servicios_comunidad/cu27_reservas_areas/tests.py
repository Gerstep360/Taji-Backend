"""Pruebas del CU27 (T049, T050, endpoints de T096/T121/T122)."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from threading import Barrier

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Person, Role, User
from auditlog.models import AuditEvent
from community.models import CommonArea, CommonAreaBlock, CommonAreaSchedule, Reservation
from condominiums.models import Condominium, Resident
from tenancy.context import TenantContext
from tenancy.models import TenantMembership

from . import services

BASE = "/api/v1/paquete5/cu27"


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)), timezone.get_current_timezone())


class SubtractIntervalsTests(TestCase):
    def test_subtract_handles_overlaps_edges_and_gaps(self):
        day = timezone.localdate() + timedelta(days=3)
        windows = [(at(day, 8), at(day, 12)), (at(day, 14), at(day, 20))]
        busy = [(at(day, 9), at(day, 10)), (at(day, 9, 30), at(day, 11)), (at(day, 14), at(day, 15)), (at(day, 19), at(day, 21))]
        self.assertEqual(
            services.subtract_intervals(windows, busy),
            [(at(day, 8), at(day, 9)), (at(day, 11), at(day, 12)), (at(day, 15), at(day, 19))],
        )


class Cu27ApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Condominium.objects.create(name="CU27 Condominio A")
        cls.other = Condominium.objects.create(name="CU27 Condominio B")
        cls.admin = cls.make_user("cu27-admin@taji.test", "administrador")
        cls.neighbor = cls.make_user("cu27-vecino@taji.test", "residente")
        cls.second = cls.make_user("cu27-vecina@taji.test", "residente")
        cls.guard = cls.make_user("cu27-guardia@taji.test", "seguridad")
        cls.resident = Resident.objects.create(condominium=cls.tenant, person=cls.neighbor.person)
        cls.resident2 = Resident.objects.create(condominium=cls.tenant, person=cls.second.person)
        cls.area = CommonArea.objects.create(condominium=cls.tenant, name="CU27 Salón")
        cls.approval_area = CommonArea.objects.create(condominium=cls.tenant, name="CU27 Churrasquera", requires_approval=True)
        cls.foreign_area = CommonArea.objects.create(condominium=cls.other, name="CU27 Ajena")
        cls.day = timezone.localdate() + timedelta(days=3)
        for area in (cls.area, cls.approval_area):
            CommonAreaSchedule.objects.create(common_area=area, weekday=cls.day.weekday(), opens_at=time(8), closes_at=time(22))

    @classmethod
    def make_user(cls, email, role):
        person = Person.objects.create(first_name=email.split("@")[0], last_name="Prueba")
        user = User.objects.create_user(email=email, password="Testing-Cu27-123!", person=person,
                                        role=Role.objects.get(slug=role), is_approved=True)
        TenantMembership.objects.create(user=user, condominium=cls.tenant, role=user.role, is_default=True)
        return user

    def setUp(self):
        TenantContext.clear()
        self.addCleanup(TenantContext.clear)
        self.client.force_authenticate(user=self.neighbor)

    # -- helpers ----------------------------------------------------------
    def as_user(self, user):
        self.client.force_authenticate(user=user)

    def payload(self, area=None, start=10, end=12, **extra):
        return {
            "common_area": (area or self.area).pk,
            "start_at": at(self.day, start).isoformat(),
            "end_at": at(self.day, end).isoformat(),
            **extra,
        }

    def reserve(self, **kwargs):
        return self.client.post(f"{BASE}/reservations/", self.payload(**kwargs), format="json")

    def act(self, pk, name, **data):
        return self.client.post(f"{BASE}/reservations/{pk}/{name}/", data, format="json")

    # -- creación y T050 --------------------------------------------------
    def test_resident_reservation_is_auto_approved_or_pending_by_area(self):
        direct = self.reserve()
        self.assertEqual(direct.status_code, 201, direct.data)
        self.assertEqual(direct.data["status"], "APPROVED")
        self.assertEqual(direct.data["resident"], self.resident.pk)
        self.assertTrue(direct.data["is_mine"])
        pending = self.reserve(area=self.approval_area)
        self.assertEqual(pending.status_code, 201, pending.data)
        self.assertEqual(pending.data["status"], "PENDING")
        self.assertFalse(pending.data["permissions"]["approve"])
        self.assertTrue(pending.data["permissions"]["cancel"])
        self.assertTrue(AuditEvent.objects.filter(action_code="CU27_RESERVATION_CREATED").exists())

    def test_overlap_is_rejected_but_adjacent_slot_is_allowed(self):
        self.assertEqual(self.reserve().status_code, 201)
        self.as_user(self.second)
        self.assertEqual(self.reserve(start=11, end=13).status_code, 400)
        self.assertEqual(self.reserve(start=9, end=11).status_code, 400)
        self.assertEqual(self.reserve(start=10, end=12).status_code, 400)
        self.assertEqual(self.reserve(start=12, end=13).status_code, 201)
        self.assertEqual(self.reserve(start=8, end=10).status_code, 201)

    def test_pending_reservation_also_holds_the_slot(self):
        self.assertEqual(self.reserve(area=self.approval_area).status_code, 201)
        self.as_user(self.second)
        self.assertEqual(self.reserve(area=self.approval_area, start=11, end=12).status_code, 400)

    def test_cancelled_or_rejected_reservations_free_the_slot(self):
        first = self.reserve().data
        self.assertEqual(self.act(first["id"], "cancel").status_code, 200)
        self.as_user(self.second)
        self.assertEqual(self.reserve().status_code, 201)

    def test_slot_rules_schedule_block_duration_past_and_status(self):
        self.assertEqual(self.reserve(start=6, end=9).status_code, 400)       # fuera de horario
        self.assertEqual(self.reserve(start=21, end=23).status_code, 400)     # cierra a las 22
        response = self.client.post(f"{BASE}/reservations/", {
            "common_area": self.area.pk,
            "start_at": at(self.day, 10).isoformat(),
            "end_at": at(self.day, 10, 15).isoformat(),
        }, format="json")
        self.assertEqual(response.status_code, 400)                          # < 30 minutos
        other_day = self.day + timedelta(days=1)
        response = self.client.post(f"{BASE}/reservations/", {
            "common_area": self.area.pk,
            "start_at": at(other_day, 10).isoformat(),
            "end_at": at(other_day, 11).isoformat(),
        }, format="json")
        self.assertEqual(response.status_code, 400)                          # día sin horario
        past = timezone.localdate() - timedelta(days=1)
        response = self.client.post(f"{BASE}/reservations/", {
            "common_area": self.area.pk,
            "start_at": at(past, 10).isoformat(),
            "end_at": at(past, 11).isoformat(),
        }, format="json")
        self.assertEqual(response.status_code, 400)                          # pasado
        CommonAreaBlock.objects.create(common_area=self.area, blocked_from=at(self.day, 15),
                                       blocked_until=at(self.day, 17), reason="Pintura")
        self.assertEqual(self.reserve(start=16, end=18).status_code, 400)     # bloqueo
        self.area.status = CommonArea.Status.MAINTENANCE
        self.area.save()
        self.assertEqual(self.reserve().status_code, 400)                     # área no disponible

    def test_resident_cannot_book_for_someone_else_or_foreign_area(self):
        self.assertEqual(self.reserve(resident=self.resident2.pk).status_code, 403)
        self.assertEqual(self.reserve(area=self.foreign_area).status_code, 400)
        self.as_user(self.guard)
        self.assertEqual(self.reserve().status_code, 403)

    def test_manager_can_book_for_resident_and_it_is_approved(self):
        self.as_user(self.admin)
        response = self.reserve(area=self.approval_area, resident=self.resident2.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "APPROVED")
        self.assertEqual(response.data["resident"], self.resident2.pk)
        self.assertEqual(self.reserve(start=14, end=15).status_code, 400)  # admin sin perfil de residente

    # -- ciclo de vida T049 ----------------------------------------------
    def test_full_approval_lifecycle_and_permissions(self):
        pending = self.reserve(area=self.approval_area).data
        self.assertEqual(self.act(pending["id"], "approve").status_code, 403)
        self.as_user(self.admin)
        approved = self.act(pending["id"], "approve")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "APPROVED")
        self.assertTrue(approved.data["decided_by_name"])
        self.assertEqual(self.act(pending["id"], "approve").status_code, 400)
        self.assertEqual(self.act(pending["id"], "reject", reason="Tarde").status_code, 400)
        self.assertEqual(self.act(pending["id"], "complete").status_code, 400)  # aún no comienza

    def test_reject_requires_reason_and_stores_it(self):
        pending = self.reserve(area=self.approval_area).data
        self.as_user(self.admin)
        self.assertEqual(self.act(pending["id"], "reject").status_code, 400)
        response = self.act(pending["id"], "reject", reason="Evento privado de la administración")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "REJECTED")
        self.assertEqual(response.data["rejection_reason"], "Evento privado de la administración")

    def test_cancel_rules_for_owner_other_resident_and_manager(self):
        mine = self.reserve().data
        self.as_user(self.second)
        self.assertEqual(self.act(mine["id"], "cancel").status_code, 404)
        self.as_user(self.admin)
        self.assertEqual(self.act(mine["id"], "cancel").status_code, 400)  # admin debe dar motivo
        response = self.act(mine["id"], "cancel", reason="Corte de agua programado")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "CANCELLED")
        self.assertEqual(response.data["cancellation_reason"], "Corte de agua programado")
        self.assertEqual(self.act(mine["id"], "cancel", reason="Otra vez").status_code, 400)

    def test_owner_cannot_cancel_after_start_and_manager_completes(self):
        reservation = Reservation.objects.create(
            common_area=self.area, resident=self.resident, status="APPROVED",
            start_at=timezone.now() - timedelta(minutes=30), end_at=timezone.now() + timedelta(hours=1),
        )
        self.assertEqual(self.act(reservation.pk, "cancel").status_code, 400)
        self.assertEqual(self.act(reservation.pk, "complete").status_code, 403)
        self.as_user(self.admin)
        response = self.act(reservation.pk, "complete")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "COMPLETED")
        self.assertIsNotNone(response.data["completed_at"])

    def test_approve_fails_if_area_was_blocked_after_request(self):
        pending = self.reserve(area=self.approval_area).data
        CommonAreaBlock.objects.create(common_area=self.approval_area, blocked_from=at(self.day, 9),
                                       blocked_until=at(self.day, 11), reason="Fumigación")
        self.as_user(self.admin)
        self.assertEqual(self.act(pending["id"], "approve").status_code, 400)

    def test_sync_expired_completes_and_expires(self):
        now = timezone.now()
        done = Reservation.objects.create(common_area=self.area, resident=self.resident, status="APPROVED",
                                          start_at=now - timedelta(hours=3), end_at=now - timedelta(hours=1))
        stale = Reservation.objects.create(common_area=self.approval_area, resident=self.resident, status="PENDING",
                                           start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1))
        response = self.client.get(f"{BASE}/reservations/")
        self.assertEqual(response.status_code, 200)
        done.refresh_from_db(); stale.refresh_from_db()
        self.assertEqual(done.status, "COMPLETED")
        self.assertEqual(stale.status, "REJECTED")
        self.assertEqual(stale.rejection_reason, services.EXPIRED_PENDING_REASON)

    # -- consultas ---------------------------------------------------------
    def test_listing_is_scoped_to_owner_and_filters_work(self):
        self.reserve()
        self.as_user(self.second)
        self.reserve(start=14, end=15)
        self.assertEqual(self.client.get(f"{BASE}/reservations/").data["pagination"]["total_items"], 1)
        self.as_user(self.admin)
        self.assertEqual(self.client.get(f"{BASE}/reservations/").data["pagination"]["total_items"], 2)
        filtered = self.client.get(f"{BASE}/reservations/", {"status": "APPROVED", "when": "upcoming"})
        self.assertEqual(filtered.data["pagination"]["total_items"], 2)
        self.assertEqual(self.client.get(f"{BASE}/reservations/", {"status": "BAD"}).status_code, 400)
        self.assertEqual(self.client.get(f"{BASE}/reservations/", {"date_from": "2020-13-01"}).status_code, 400)

    def test_availability_lists_free_slots_and_hides_other_residents(self):
        self.as_user(self.second)
        self.reserve(start=10, end=12)
        self.as_user(self.neighbor)
        response = self.client.get(f"{BASE}/areas/{self.area.pk}/availability/", {"date": self.day.isoformat()})
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertTrue(data["bookable"])
        self.assertEqual(len(data["free"]), 2)
        self.assertEqual(data["free"][0]["start"], at(self.day, 8).isoformat())
        self.assertEqual(data["free"][0]["end"], at(self.day, 10).isoformat())
        self.assertEqual(data["free"][1]["start"], at(self.day, 12).isoformat())
        occupied = data["occupied"][0]
        self.assertEqual(occupied["label"], "Reservado")
        self.assertIsNone(occupied["id"])
        closed = self.client.get(f"{BASE}/areas/{self.area.pk}/availability/",
                                 {"date": (self.day + timedelta(days=1)).isoformat()})
        self.assertFalse(closed.data["bookable"])
        self.assertEqual(closed.data["reason"], "El área no atiende este día.")
        self.assertEqual(self.client.get(f"{BASE}/areas/{self.foreign_area.pk}/availability/").status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}/areas/{self.area.pk}/availability/", {"date": "x"}).status_code, 400)

    def test_areas_list_is_tenant_scoped_and_hides_inactive(self):
        CommonArea.objects.create(condominium=self.tenant, name="CU27 Inactiva", status="INACTIVE")
        response = self.client.get(f"{BASE}/areas/")
        self.assertEqual(response.status_code, 200)
        names = {item["name"] for item in response.data["results"]}
        self.assertEqual(names, {"CU27 Salón", "CU27 Churrasquera"})
        self.assertEqual(len(response.data["results"][0]["schedules"]), 1)

    def test_calendar_and_summary_are_for_managers_only(self):
        self.reserve()
        self.reserve(area=self.approval_area, start=14, end=15)
        self.assertEqual(self.client.get(f"{BASE}/reservations/calendar/").status_code, 403)
        self.assertEqual(self.client.get(f"{BASE}/reservations/summary/").status_code, 403)
        self.as_user(self.admin)
        response = self.client.get(f"{BASE}/reservations/calendar/", {
            "date_from": timezone.localdate().isoformat(), "date_to": (self.day + timedelta(days=1)).isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["reservations"]), 2)
        self.assertEqual(self.client.get(f"{BASE}/reservations/calendar/", {
            "date_from": "2026-01-01", "date_to": "2026-06-01"}).status_code, 400)
        summary = self.client.get(f"{BASE}/reservations/summary/").data
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["next_7_days"], 2)
        residents = self.client.get(f"{BASE}/residents/", {"search": "vecina"})
        self.assertEqual([r["id"] for r in residents.data], [self.resident2.pk])


@unittest.skipUnless(connection.vendor == "postgresql", "La restricción EXCLUDE solo existe en PostgreSQL.")
class PostgresExclusionTests(TestCase):
    """T050: la base de datos rechaza cruces aunque se salte la lógica de la API."""

    def test_database_rejects_overlapping_active_reservations(self):
        tenant = Condominium.objects.create(name="CU27 PG")
        person = Person.objects.create(first_name="PG", last_name="Prueba")
        resident = Resident.objects.create(condominium=tenant, person=person)
        area = CommonArea.objects.create(condominium=tenant, name="CU27 PG Salón")
        start = timezone.now() + timedelta(days=2)
        Reservation.objects.create(common_area=area, resident=resident, start_at=start,
                                   end_at=start + timedelta(hours=2), status="APPROVED")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reservation.objects.create(common_area=area, resident=resident, start_at=start + timedelta(hours=1),
                                       end_at=start + timedelta(hours=3), status="PENDING")
        Reservation.objects.create(common_area=area, resident=resident, start_at=start + timedelta(hours=1),
                                   end_at=start + timedelta(hours=3), status="CANCELLED")


@unittest.skipUnless(connection.vendor == "postgresql", "Requiere dos transacciones en PostgreSQL.")
class PostgresConcurrentReservationTests(TransactionTestCase):
    def test_only_one_concurrent_overlapping_reservation_commits(self):
        tenant = Condominium.objects.create(name="CU27 PG concurrente")
        area = CommonArea.objects.create(condominium=tenant, name="Salón concurrente")
        residents = [
            Resident.objects.create(condominium=tenant, person=Person.objects.create(first_name=name))
            for name in ("Primero", "Segundo")
        ]
        start = timezone.now() + timedelta(days=2)
        ready = Barrier(2, timeout=10)

        def reserve(entry):
            index, resident = entry
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL statement_timeout = '10s'")
                    if index:
                        ready.wait()
                    Reservation.objects.create(common_area_id=area.pk, resident_id=resident.pk,
                                               start_at=start, end_at=start + timedelta(hours=1), status="PENDING")
                    if not index:
                        ready.wait()
                return "committed"
            except IntegrityError as exc:
                self.assertEqual(exc.__cause__.diag.constraint_name, "ex_reservation_no_overlap")
                return "blocked"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, enumerate(residents)))
        self.assertCountEqual(results, ["committed", "blocked"])
        self.assertEqual(Reservation.objects.filter(common_area=area).count(), 1)
