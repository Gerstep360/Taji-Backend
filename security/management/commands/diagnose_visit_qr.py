"""
Diagnostica por que `POST /visit-qr/<pk>/generate/` responde 503 en el servidor.

El manejador de errores de la API traduce cualquier `DatabaseError` a un 503
"La base de datos no esta disponible" y descarta el traceback. Sin el log
correspondiente no hay forma de saber si es una conexion muerta, un bloqueo de
fila o un dato que no entra en su columna, y las tres secorrigen distinto.

Este comando reconstruye el mismo camino que la vista (validacion de estado,
calculo de vigencia, `select_for_update` y guardado) dentro de una transaccion
que SIEMPRE se revierte, e imprime el traceback real si algo falla. No modifica
datos: sirve para diagnostico, no para operar.
"""

import traceback
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from security.models import VisitAuthorization
from security.qr import (
    VisitQrError,
    _lock_authorization,
    _resolve_ttl,
    build_payload,
    generate_token,
    hash_token,
    render_qr_image,
)


class Command(BaseCommand):
    help = (
        "Reproduce la emision de un pase QR e imprime el error real que el servidor "
        "traduce a un 503. No modifica datos."
    )

    def add_arguments(self, parser):
        parser.add_argument("pk", type=int, help="ID de la autorizacion de visita.")
        parser.add_argument(
            "--ttl-minutes",
            type=int,
            default=None,
            help="Vigencia a probar, como en el parametro `ttl_minutes` de la API.",
        )

    def handle(self, *args, **options):
        pk = options["pk"]
        self._report_connection()

        authorization = self._load(pk)
        if authorization is None:
            raise CommandError(f"No existe la autorizacion de visita {pk}.")

        self._report_authorization(authorization)

        rejection = self._check_business_rules(authorization, options.get("ttl_minutes"))
        if rejection is not None:
            self.stdout.write(
                self.style.WARNING(
                    "El backend responderia 400, no 503:\n  " + rejection
                )
            )
            return

        self._report_locks()
        self._reproduce_write(authorization, options.get("ttl_minutes"))

    # ------------------------------------------------------------------ lecturas

    def _report_connection(self):
        info = connection.settings_dict
        self.stdout.write(self.section("Conexion"))
        self.stdout.write(f"  motor:    {info.get('ENGINE')}")
        self.stdout.write(f"  base:     {info.get('NAME')}")
        self.stdout.write(f"  host:     {info.get('HOST')}:{info.get('PORT')}")
        # `CONN_HEALTH_CHECKS` ausente es la causa mas frecuente de un 503 que
        # aparece y desaparece: Gunicorn reutiliza una conexion que PostgreSQL
        # ya cerro (por ejemplo tras el reinicio que hace el propio despliegue).
        self.stdout.write(
            f"  CONN_MAX_AGE:      {info.get('CONN_MAX_AGE')}"
        )
        self.stdout.write(
            f"  CONN_HEALTH_CHECKS: {info.get('CONN_HEALTH_CHECKS')}"
            + (
                ""
                if info.get("CONN_HEALTH_CHECKS")
                else "   <-- ACTIVAR: sin esto una conexion muerta se reutiliza"
            )
        )

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                self.stdout.write(f"  servidor: {cursor.fetchone()[0].split(',')[0]}")
                cursor.execute("SHOW statement_timeout")
                self.stdout.write(f"  statement_timeout: {cursor.fetchone()[0]}")
                cursor.execute("SHOW lock_timeout")
                self.stdout.write(f"  lock_timeout:      {cursor.fetchone()[0]}")
        except DatabaseError as exc:
            self.stdout.write(self.style.ERROR(f"  No se pudo consultar el servidor: {exc}"))
            return

    def _load(self, pk: int):
        try:
            return VisitAuthorization.objects.select_related(
                "visitor_person",
                "authorized_by_resident__person",
                "unit__sector",
            ).get(pk=pk)
        except VisitAuthorization.DoesNotExist:
            return None
        except DatabaseError:
            self.stdout.write(self.style.ERROR("No se pudo LEER la autorizacion:"))
            self.stdout.write(traceback.format_exc())
            raise CommandError("Fallo la lectura; el traceback esta arriba.")

    def _report_authorization(self, authorization):
        now = timezone.now()
        self.stdout.write(self.section("Autorizacion"))
        self.stdout.write(f"  id:            {authorization.pk}")
        self.stdout.write(f"  status:        {authorization.status}")
        self.stdout.write(f"  valid_from:    {authorization.valid_from}")
        self.stdout.write(f"  valid_until:   {authorization.valid_until}")
        self.stdout.write(f"  ahora:         {now}")
        self.stdout.write(
            f"  minutos hasta el fin: "
            f"{int((authorization.valid_until - now).total_seconds() // 60)}"
        )
        self.stdout.write(f"  qr_issued_at:  {authorization.qr_issued_at}")
        self.stdout.write(f"  qr_expires_at: {authorization.qr_expires_at}")
        self.stdout.write(f"  visitor:       {authorization.visitor_person_id}")
        self.stdout.write(f"  unidad:        {authorization.unit_id}")
        # Longitudes reales: un valor que no entra en su columna produce un
        # `DataError` (subclase de `DatabaseError`) y por tanto un 503.
        self.stdout.write(self.section("Longitudes de columnas"))
        for field in ("purpose", "qr_token_hash", "qr_uuid", "status"):
            column = VisitAuthorization._meta.get_field(field)
            self.stdout.write(
                f"  {field:<16} {type(column).__name__}"
                + (f"({column.max_length})" if hasattr(column, "max_length") else "")
            )
        token = generate_token()
        self.stdout.write(
            f"  hash de un token nuevo: {len(hash_token(token))} caracteres"
        )

    def _check_business_rules(self, authorization, ttl_minutes):
        """Devuelve el motivo del 400 si lo hay; None si la emision es valida."""
        if authorization.status in (
            VisitAuthorization.Status.CANCELLED,
            VisitAuthorization.Status.FINISHED,
            VisitAuthorization.Status.EXPIRED,
        ):
            return (
                f"status_not_allowed: no se puede emitir un QR en estado "
                f"{authorization.get_status_display()}."
            )
        try:
            ttl = _resolve_ttl(authorization, ttl_minutes, timezone.now())
        except VisitQrError as exc:
            return f"{exc.code}: {exc.message}"
        self.stdout.write(self.section("Vigencia calculada"))
        self.stdout.write(f"  ttl efectivo: {ttl} minutos")
        return None

    def _report_locks(self):
        """Una fila bloqueada por otra transacion hace fallar el `select_for_update`."""
        self.stdout.write(self.section("Bloqueos y transacciones abiertas"))
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pid, state, wait_event_type, wait_event,
                           EXTRACT(EPOCH FROM (now() - xact_start))::int AS segundos,
                           left(query, 90)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid <> pg_backend_pid()
                      AND xact_start IS NOT NULL
                    ORDER BY xact_start
                    """
                )
                rows = cursor.fetchall()
        except DatabaseError:
            # Sin permisos de superusuario esta vista puede estar restringida; no
            # es motivo para abortar el diagnostico.
            self.stdout.write("  (no se pudo consultar pg_stat_activity)")
            return

        if not rows:
            self.stdout.write("  ninguna otra transaccion abierta")
            return
        for pid, state, wait_type, wait_event, seconds, query in rows:
            self.stdout.write(
                f"  pid={pid} state={state} espera={wait_type}/{wait_event} "
                f"abierta hace {seconds}s"
            )
            self.stdout.write(f"      {query}")

    # ------------------------------------------------------------------ escritura

    def _reproduce_write(self, authorization, ttl_minutes):
        """
        Ejecuta el guardado real dentro de una transaccion que se revierte.

        Es el unico modo de obtener el traceback del 503 sin tocar los datos: el
        error se reproduce con la misma fila y las mismas columnas que en el
        servidor, y la reversion lo deja todo como estaba.

        La reversion es explicita (`set_rollback`) y no `atomic.__exit__(None,
        ...)`: al salir sin excepcion Django **confirma** el savepoint, de modo
        que esa forma habria dejado emitido el QR de verdad mientras el comando
        anuncia lo contrario.
        """
        self.stdout.write(self.section("Escritura (se revierte al terminar)"))
        try:
            with transaction.atomic():
                now = timezone.now()
                ttl = _resolve_ttl(authorization, ttl_minutes, now)
                token = generate_token()
                new_expiry = min(now + timedelta(minutes=ttl), authorization.valid_until)

                # Se usa el mismo helper que la vista, no un `select_for_update()`
                # propio: el diagnostico solo es util si reproduce exactamente la
                # sentencia que falla en el servidor.
                locked = _lock_authorization(authorization.pk)
                locked.qr_token_hash = hash_token(token)
                locked.qr_issued_at = now
                locked.qr_expires_at = new_expiry
                locked.save(
                    update_fields=["qr_token_hash", "qr_issued_at", "qr_expires_at"]
                )
                self.stdout.write(self.style.SUCCESS("  el guardado funciono"))

                # El render de la imagen tambien ocurre en la vista y un fallo
                # aqui seria otro 500 (no un 503, pero conviene separarlos).
                payload = build_payload(locked.qr_uuid, token)
                image, media = render_qr_image(payload, "svg")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  la imagen se genero ({media}, {len(image)} bytes)"
                    )
                )
                transaction.set_rollback(True)
        except DatabaseError:
            self.stdout.write(self.style.ERROR("  ESTE es el error que produce el 503:"))
            self.stdout.write(traceback.format_exc())
            self.stdout.write(self.section("Cola del traceback"))
            self.stdout.write("  (lo de arriba es lo que el servidor responde como 503)")
        except Exception:
            self.stdout.write(self.style.ERROR("  Error distinto a un problema de base:"))
            self.stdout.write(traceback.format_exc())
        finally:
            self.stdout.write("  transaccion revertida: los datos no cambiaron")

    # ------------------------------------------------------------------ utilidades

    def section(self, title: str) -> str:
        return self.style.MIGRATE_HEADING(f"\n== {title} ==")
