"""
Contrato del manejador de errores de la API, con foco en la trazabilidad.

Un 503 sin detalle es el peor tipo de fallo: el usuario ve "La base de datos no
esta disponible" y el operador no sabe que peticion fue. Estos tests fijan que el
`trace_id` y el nombre de la excepcion viajen en la respuesta y queden en el log,
que es lo que permite emparejar los dos.
"""

from django.db.utils import DataError, OperationalError
from django.test import RequestFactory, SimpleTestCase

from config.api import taji_exception_handler


class UnhandledErrorDiagnosticsTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _handle(self, exc, path="/api/v1/visit-qr/3/generate/"):
        request = self.factory.post(path)
        return taji_exception_handler(exc, {"view": None, "request": request})

    def test_a_503_carries_a_trace_id_and_the_exception_name(self):
        response = self._handle(DataError("value too long for character varying(64)"))

        self.assertEqual(response.status_code, 503)
        error = response.data["error"]
        self.assertEqual(error["code"], "service_unavailable")
        self.assertTrue(error["trace_id"])
        self.assertEqual(error["exception"], "DataError")

    def test_the_trace_id_reaches_the_log_with_the_request_line(self):
        """Sin esto el trace_id no sirve: nadie podria emparejarlo."""
        with self.assertLogs("taji.api", level="ERROR") as captured:
            self._handle(OperationalError("server closed the connection unexpectedly"))

        line = "\n".join(captured.output)
        self.assertIn("trace_id=", line)
        self.assertIn("OperationalError", line)
        # El metodo y la ruta permiten localizar cual de las peticiones fallo.
        self.assertIn("POST", line)
        self.assertIn("/api/v1/visit-qr/3/generate/", line)

    def test_the_message_never_leaks_sql(self):
        with self.assertLogs("taji.api", level="ERROR"):
            response = self._handle(
                DataError('value too long for type character varying(64)')
            )

        self.assertEqual(
            response.data["error"]["message"],
            "La base de datos no está disponible temporalmente.",
        )

    def test_each_failure_gets_its_own_trace_id(self):
        with self.assertLogs("taji.api", level="ERROR"):
            first = self._handle(DataError("a")).data["error"]["trace_id"]
            second = self._handle(DataError("b")).data["error"]["trace_id"]

        self.assertNotEqual(first, second)

    def test_business_errors_carry_no_diagnostics(self):
        """
        Un 400 de negocio no lleva `trace_id`: no hay traceback que rastreary
        anadir un id al azar solo confunde.
        """
        from rest_framework.exceptions import ValidationError

        response = taji_exception_handler(
            ValidationError({"status_not_allowed": ["Visita expirada."]}),
            {"view": None, "request": self.factory.post("/x/")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("trace_id", response.data["error"])
        self.assertNotIn("exception", response.data["error"])
        # El motivo de negocio si debe viajar intacto.
        self.assertIn("status_not_allowed", response.data["error"]["fields"])

    def test_an_unexpected_error_also_gets_a_trace_id(self):
        with self.assertLogs("taji.api", level="ERROR"):
            response = self._handle(TypeError("'NoneType' object is not subscriptable"))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"]["exception"], "TypeError")
        self.assertTrue(response.data["error"]["trace_id"])
