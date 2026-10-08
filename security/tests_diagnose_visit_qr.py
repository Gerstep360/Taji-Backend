"""
Pruebas del comando `diagnose_visit_qr`.

Lo que importa no es solo que arranque, sino que **revele** el error que la API
convierte en un 503 generico. La segunda prueba lo comprueba forzando un
`DataError` real: si el comando no lo mostra, no sirve para el diagnostico que se
hizo.
"""

import io
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.utils import DataError, OperationalError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Person
from condominiums.models import Condominium, Resident, Sector, Unit
from security.management.commands import diagnose_visit_qr as command_module
from security.models import VisitAuthorization


class DiagnoseVisitQrTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        condominium = Condominium.objects.create(name="Taji Diagnostico")
        sector = Sector.objects.create(condominium=condominium, code="TORRE-A", name="Torre A")
        cls.unit = Unit.objects.create(
            sector=sector, code="C-04", unit_type=Unit.Type.APARTMENT
        )
        cls.visitor = Person.objects.create(
            first_name="Carlos", last_name="Visitante", document_number="7654321"
        )
        host_person = Person.objects.create(
            first_name="Ana", last_name="Propietaria", document_number="7654322"
        )
        cls.resident = Resident.objects.create(
            person=host_person,
            condominium=condominium,
            status=Resident.Status.ACTIVE,
        )

    def _authorization(self, *, valid_until, status=VisitAuthorization.Status.AUTHORIZED):
        return VisitAuthorization.objects.create(
            visitor_person=self.visitor,
            authorized_by_resident=self.resident,
            unit=self.unit,
            purpose="Visita de prueba",
            valid_from=timezone.now() - timedelta(hours=1),
            valid_until=valid_until,
            qr_expires_at=valid_until,
            status=status,
        )

    def _run(self, pk, **kwargs):
        out = io.StringIO()
        call_command("diagnose_visit_qr", pk, stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    def test_reports_a_healthy_authorization_without_touching_it(self):
        authorization = self._authorization(valid_until=timezone.now() + timedelta(hours=3))

        output = self._run(authorization.pk)

        self.assertIn("el guardado funciono", output)
        self.assertIn("la imagen se genero", output)
        self.assertIn("transaccion revertida", output)
        # Lo esencial: la reversion no deja rastro.
        authorization.refresh_from_db()
        self.assertIsNone(authorization.qr_issued_at)
        self.assertIsNone(authorization.qr_token_hash)

    def test_surfaces_the_real_database_error_behind_a_503(self):
        """
        Un `DataError` (un valor que no cabe en su columna) es subclase de
        `DatabaseError`, asi que sale de la API como 503 y sin detalle. El comando
        debe imprimirlo con su nombre y su mensaje, que es justo lo que hace
        falta para distinguirlo de un `OperationalError`.

        La excepcion se inyecta en el `save` en lugar de confiar en un hash
        sobredimensionado: SQLite no aplica `max_length`, asi que un valor largo
        pasaria sin error y el test no probaria nada.
        """
        authorization = self._authorization(valid_until=timezone.now() + timedelta(hours=3))
        boom = DataError('value too long for type character varying(64)')

        with mock.patch(
            "django.db.models.Model.save", side_effect=boom
        ):
            output = self._run(authorization.pk)

        self.assertIn("ESTE es el error que produce el 503", output)
        self.assertIn("DataError", output)
        self.assertIn("character varying(64)", output)
        self.assertIn("transaccion revertida", output)

    def test_a_dead_connection_is_reported_as_operational_error(self):
        """
        La otra causa de 503: una conexion que PostgreSQL ya cerro. El mensaje
        que produce es caracteristico y debe llegar al diagnostico.
        """
        authorization = self._authorization(valid_until=timezone.now() + timedelta(hours=3))
        boom = OperationalError(
            "server closed the connection unexpectedly"
        )

        with mock.patch("django.db.models.Model.save", side_effect=boom):
            output = self._run(authorization.pk)

        self.assertIn("OperationalError", output)
        self.assertIn("server closed the connection unexpectedly", output)

    def test_explains_a_400_instead_of_hunting_for_a_503(self):
        """Una visita expirada daria 400, no 503: decirlo ahorra tiempo."""
        authorization = self._authorization(valid_until=timezone.now() + timedelta(hours=2))
        VisitAuthorization.objects.filter(pk=authorization.pk).update(
            status=VisitAuthorization.Status.EXPIRED
        )

        output = self._run(authorization.pk)

        self.assertIn("responderia 400, no 503", output)
        self.assertIn("status_not_allowed", output)

    def test_explains_a_window_with_no_room_left(self):
        authorization = self._authorization(valid_until=timezone.now() + timedelta(minutes=2))

        output = self._run(authorization.pk)

        self.assertIn("visit_window_ended", output)

    def test_rejects_a_missing_authorization(self):
        with self.assertRaises(CommandError):
            self._run(987654)

    def test_warns_when_connection_health_checks_are_off(self):
        """
        Sin `CONN_HEALTH_CHECKS`, la causa mas probable de un 503 intermitente
        queda a un comando de distancia. El aviso debe verse aunque el guardado
        funcione bien, porque el fallo ocurre en el servidor, no aqui.
        """
        authorization = self._authorization(valid_until=timezone.now() + timedelta(hours=3))
        info = {**command_module.connection.settings_dict, "CONN_HEALTH_CHECKS": False}
        with mock.patch.object(command_module.connection, "settings_dict", info):
            output = self._run(authorization.pk)

        self.assertIn("CONN_HEALTH_CHECKS", output)
        self.assertIn("ACTIVAR", output)
