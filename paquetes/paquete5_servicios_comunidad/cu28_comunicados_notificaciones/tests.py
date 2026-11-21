from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import Person, Role, SystemPermission, User
from condominiums.models import Condominium
from notifications.models import Announcement, DeviceToken, Notification
from tenancy.context import TenantContext
from tenancy.models import TenantMembership


class Cu28ComunicadosNotificacionesTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant_a = Condominium.objects.create(name="Condominio A")
        cls.tenant_b = Condominium.objects.create(name="Condominio B")

        # Asegurar permisos en roles
        perm_manage, _ = SystemPermission.objects.get_or_create(
            code="manage_announcements",
            defaults={"name": "Gestionar comunicados", "module": "community"},
        )
        admin_role = Role.objects.get(slug="administrador")
        admin_role.permissions.add(perm_manage)

        # Usuarios en Tenant A
        cls.admin_a = cls.make_user("admin-a@taji.test", "administrador", cls.tenant_a)
        cls.resident_a1 = cls.make_user("res1-a@taji.test", "residente", cls.tenant_a)
        cls.resident_a2 = cls.make_user("res2-a@taji.test", "residente", cls.tenant_a)
        cls.guard_a = cls.make_user("guard-a@taji.test", "seguridad", cls.tenant_a)

        # Usuario en Tenant B (para pruebas de aislamiento multi-tenant)
        cls.admin_b = cls.make_user("admin-b@taji.test", "administrador", cls.tenant_b)
        cls.resident_b = cls.make_user("res-b@taji.test", "residente", cls.tenant_b)

    @classmethod
    def make_user(cls, email: str, role_slug: str, condo: Condominium) -> User:
        person = Person.objects.create(
            first_name=email.split("@")[0], last_name="Tester"
        )
        role = Role.objects.get(slug=role_slug)
        user = User.objects.create_user(
            email=email,
            password="TestPassword123!",
            person=person,
            role=role,
            is_approved=True,
        )
        TenantMembership.objects.create(
            user=user,
            condominium=condo,
            role=role,
            is_default=True,
            is_active=True,
        )
        return user

    def setUp(self):
        TenantContext.clear()
        self.addCleanup(TenantContext.clear)

    # -------------------------------------------------------------
    # ESCENARIO 1: Creación de comunicados por audiencia y prioridad (T051)
    # -------------------------------------------------------------
    def test_admin_can_create_draft_and_published_announcements(self):
        self.client.force_authenticate(user=self.admin_a)

        # Creación en estado BORRADOR
        payload_draft = {
            "title": "Mantenimiento preventivo ascensores",
            "body": "El ascensor torre 1 estará fuera de servicio el jueves de 9 a 12.",
            "audience": "RESIDENTS",
            "priority": "HIGH",
            "status": "DRAFT",
        }
        res_draft = self.client.post(
            "/api/v1/paquete5/cu28/announcements/", payload_draft, format="json"
        )
        self.assertEqual(res_draft.status_code, 201)
        self.assertEqual(res_draft.data["title"], payload_draft["title"])
        self.assertEqual(res_draft.data["status"], "DRAFT")
        self.assertEqual(res_draft.data["audience"], "RESIDENTS")
        self.assertEqual(res_draft.data["priority"], "HIGH")

        # Creación directamente en estado PUBLICADO
        payload_published = {
            "title": "Reunión de emergencia agua potable",
            "body": "Corte programado hoy a las 18:00.",
            "audience": "ALL",
            "priority": "URGENT",
            "status": "PUBLISHED",
        }
        res_pub = self.client.post(
            "/api/v1/paquete5/cu28/announcements/", payload_published, format="json"
        )
        self.assertEqual(res_pub.status_code, 201)
        self.assertEqual(res_pub.data["status"], "PUBLISHED")
        self.assertIsNotNone(res_pub.data["published_at"])

    def test_resident_cannot_create_announcements(self):
        self.client.force_authenticate(user=self.resident_a1)

        payload = {
            "title": "Intento de anuncio no autorizado",
            "body": "No debería permitirse.",
            "audience": "ALL",
            "priority": "NORMAL",
        }
        res = self.client.post(
            "/api/v1/paquete5/cu28/announcements/", payload, format="json"
        )
        self.assertEqual(res.status_code, 403)

    # -------------------------------------------------------------
    # ESCENARIO 2: Publicación y generación automática de notificaciones (T051 + T052)
    # -------------------------------------------------------------
    def test_publishing_announcement_generates_notifications_for_target_audience(self):
        self.client.force_authenticate(user=self.admin_a)

        # Crear como DRAFT con audiencia RESIDENTS
        ann = Announcement.objects.create(
            condominium=self.tenant_a,
            created_by_user=self.admin_a,
            title="Aviso Exclusivo Residentes",
            body="Limpieza de estacionamientos mañana.",
            audience=Announcement.Audience.RESIDENTS,
            priority=Announcement.Priority.NORMAL,
            status=Announcement.Status.DRAFT,
        )

        # Verificar que no hay notificaciones previas
        self.assertEqual(
            Notification.objects.filter(resource_id=str(ann.pk)).count(), 0
        )

        # Publicar a través del endpoint de acción /publish/
        res = self.client.post(f"/api/v1/paquete5/cu28/announcements/{ann.pk}/publish/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "PUBLISHED")

        # Verificar notificaciones generadas en la base de datos
        notifs = Notification.objects.filter(resource_id=str(ann.pk))
        notified_users = set(notifs.values_list("user_id", flat=True))

        # Debe incluir a resident_a1 y resident_a2
        self.assertIn(self.resident_a1.pk, notified_users)
        self.assertIn(self.resident_a2.pk, notified_users)
        # NO debe incluir al guardia (seguridad) porque la audiencia fue RESIDENTS
        self.assertNotIn(self.guard_a.pk, notified_users)
        # NO debe incluir a usuarios de otro condominio (Tenant B)
        self.assertNotIn(self.resident_b.pk, notified_users)

    # -------------------------------------------------------------
    # ESCENARIO 3: Filtrado y restricción por audiencia según rol (T051)
    # -------------------------------------------------------------
    def test_resident_only_sees_published_matching_audience_and_not_expired(self):
        # 1. Comunicado ALL publicado vigente
        ann_all = Announcement.objects.create(
            condominium=self.tenant_a,
            created_by_user=self.admin_a,
            title="Anuncio General",
            body="Para todos.",
            audience=Announcement.Audience.ALL,
            status=Announcement.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(hours=1),
        )
        # 2. Comunicado SECURITY publicado
        ann_sec = Announcement.objects.create(
            condominium=self.tenant_a,
            created_by_user=self.admin_a,
            title="Protocolo Ronda Nocturna",
            body="Solo para guardias.",
            audience=Announcement.Audience.SECURITY,
            status=Announcement.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(hours=1),
        )
        # 3. Comunicado RESIDENTS en BORRADOR (no debe verse)
        Announcement.objects.create(
            condominium=self.tenant_a,
            created_by_user=self.admin_a,
            title="Borrador no visible",
            body="Oculto.",
            audience=Announcement.Audience.RESIDENTS,
            status=Announcement.Status.DRAFT,
        )
        # 4. Comunicado RESIDENTS vencido (no debe verse)
        Announcement.objects.create(
            condominium=self.tenant_a,
            created_by_user=self.admin_a,
            title="Aviso ya expirado",
            body="Venció ayer.",
            audience=Announcement.Audience.RESIDENTS,
            status=Announcement.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=2),
            expires_at=timezone.now() - timedelta(days=1),
        )

        # Consultar como Residente
        self.client.force_authenticate(user=self.resident_a1)

        res = self.client.get("/api/v1/paquete5/cu28/announcements/")
        self.assertEqual(res.status_code, 200)
        returned_ids = [item["id"] for item in res.data["results"]]

        self.assertIn(ann_all.pk, returned_ids)
        self.assertNotIn(ann_sec.pk, returned_ids)
        self.assertEqual(len(returned_ids), 1)

        # Consultar como Guardia de Seguridad
        self.client.force_authenticate(user=self.guard_a)
        res_guard = self.client.get("/api/v1/paquete5/cu28/announcements/")
        self.assertEqual(res_guard.status_code, 200)
        guard_ids = [item["id"] for item in res_guard.data["results"]]

        self.assertIn(ann_all.pk, guard_ids)
        self.assertIn(ann_sec.pk, guard_ids)

    # -------------------------------------------------------------
    # ESCENARIO 4: Registro y actualización de DeviceToken (T052)
    # -------------------------------------------------------------
    def test_register_and_refresh_device_token(self):
        self.client.force_authenticate(user=self.resident_a1)

        payload = {
            "token": "fcm_token_resident_alpha_12345",
            "platform": "ANDROID",
            "is_active": True,
        }
        res1 = self.client.post("/api/v1/notifications/devices/", payload, format="json")
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res1.data["token"], payload["token"])

        # Re-registro (mismo token, cambio a iOS)
        payload["platform"] = "IOS"
        res2 = self.client.post("/api/v1/notifications/devices/", payload, format="json")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data["platform"], "IOS")

        # Verificar en base de datos
        dev = DeviceToken.objects.get(token=payload["token"])
        self.assertEqual(dev.user_id, self.resident_a1.pk)
        self.assertEqual(dev.platform, "IOS")

    # -------------------------------------------------------------
    # ESCENARIO 5: Consulta y marcado de notificaciones como leídas (T052)
    # -------------------------------------------------------------
    def test_notification_center_list_and_mark_as_read(self):
        n1 = Notification.objects.create(
            user=self.resident_a1,
            notification_type="ANNOUNCEMENT",
            title="Notificación 1",
            message="Contenido 1",
        )
        n2 = Notification.objects.create(
            user=self.resident_a1,
            notification_type="ANNOUNCEMENT",
            title="Notificación 2",
            message="Contenido 2",
        )

        self.client.force_authenticate(user=self.resident_a1)

        # Conteo de no leídas
        res_count = self.client.get("/api/v1/notifications/unread_count/")
        self.assertEqual(res_count.status_code, 200)
        self.assertEqual(res_count.data["unread_count"], 2)

        # Marcar n1 como leída
        res_read = self.client.post(f"/api/v1/notifications/{n1.pk}/mark_read/")
        self.assertEqual(res_read.status_code, 200)
        self.assertTrue(res_read.data["is_read"])

        # Recuento posterior
        res_count2 = self.client.get("/api/v1/notifications/unread_count/")
        self.assertEqual(res_count2.data["unread_count"], 1)

        # Marcar todas como leídas
        res_all = self.client.post("/api/v1/notifications/mark_all_read/")
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(res_all.data["marked_read"], 1)

        # Recuento final 0
        res_count3 = self.client.get("/api/v1/notifications/unread_count/")
        self.assertEqual(res_count3.data["unread_count"], 0)

    # -------------------------------------------------------------
    # ESCENARIO 6: Aislamiento estricto multi-tenant (T051)
    # -------------------------------------------------------------
    def test_multi_tenant_isolation_between_condominiums(self):
        ann_a = Announcement.objects.create(
            condominium=self.tenant_a,
            created_by_user=self.admin_a,
            title="Comunicado Secreto Condominio A",
            body="Detalle interno de A.",
            audience=Announcement.Audience.ALL,
            status=Announcement.Status.PUBLISHED,
        )
        ann_b = Announcement.objects.create(
            condominium=self.tenant_b,
            created_by_user=self.admin_b,
            title="Comunicado Secreto Condominio B",
            body="Detalle interno de B.",
            audience=Announcement.Audience.ALL,
            status=Announcement.Status.PUBLISHED,
        )

        # Admin A no debe ver ann_b
        self.client.force_authenticate(user=self.admin_a)

        res_a = self.client.get("/api/v1/paquete5/cu28/announcements/")
        self.assertEqual(res_a.status_code, 200)
        items_a = res_a.data.get("results", res_a.data) if isinstance(res_a.data, dict) else res_a.data
        ids_a = [item["id"] for item in items_a]
        self.assertIn(ann_a.pk, ids_a)
        self.assertNotIn(ann_b.pk, ids_a)

        # Intento de acceso directo por ID a un recurso de otro tenant
        res_detail = self.client.get(
            f"/api/v1/paquete5/cu28/announcements/{ann_b.pk}/"
        )
        self.assertEqual(res_detail.status_code, 404)
