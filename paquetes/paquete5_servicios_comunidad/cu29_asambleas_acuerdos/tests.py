import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from auditlog.models import AuditEvent
from community.models import Agreement, AgreementAttachment, Assembly
from condominiums.models import Condominium
from tenancy.models import TenantMembership

ASSEMBLIES = "/api/v1/assemblies/"
AGREEMENTS = "/api/v1/agreements/"


def fields(response):
    return response.data.get("error", {}).get("fields", response.data)


class CU29BaseTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        manage, _ = SystemPermission.objects.get_or_create(
            code="manage_assemblies", defaults={"name": "Gestionar asambleas y acuerdos"}
        )
        track, _ = SystemPermission.objects.get_or_create(
            code="track_assembly_decisions", defaults={"name": "Dar seguimiento a decisiones de asamblea"}
        )
        admin_role, _ = Role.objects.get_or_create(slug="administrador", defaults={"name": "Administrador"})
        admin_role.permissions.add(manage, track)
        directiva_role, _ = Role.objects.get_or_create(slug="directiva", defaults={"name": "Directiva"})
        directiva_role.permissions.add(track)
        resident_role, _ = Role.objects.get_or_create(slug="residente", defaults={"name": "Residente"})

        cls.condo = Condominium.objects.create(name="Condominio CU29")
        cls.other_condo = Condominium.objects.create(name="Otro condominio CU29")

        cls.admin = cls._user("admin-cu29@example.test", "Ana Admin", admin_role, cls.condo)
        cls.directiva = cls._user("directiva-cu29@example.test", "Dario Directiva", directiva_role, cls.condo)
        cls.resident = cls._user("residente-cu29@example.test", "Rosa Residente", resident_role, cls.condo)
        cls.outsider = cls._user("fuera-cu29@example.test", "Omar Otro", admin_role, cls.other_condo)

    @staticmethod
    def _user(email, name, role, condo):
        first, last = name.split(" ", 1)
        person = Person.objects.create(
            first_name=first, last_name=last, document_type=Person.DocumentType.CI,
            document_number=f"CU29-{email.split('@')[0]}",
        )
        user = User.objects.create_user(
            email=email, password="SecurePassword-123!", person=person, role=role, is_approved=True,
        )
        TenantMembership.objects.create(user=user, condominium=condo, role=role, is_default=True)
        return user

    def as_user(self, user):
        self.client.force_authenticate(user=user)

    def make_assembly(self, status_=Assembly.Status.SCHEDULED, condo=None, **extra):
        data = {
            "condominium": condo or self.condo, "title": "Asamblea general",
            "scheduled_at": timezone.now() + timedelta(days=7), "location": "Salón comunal",
            "status": status_, "created_by_user": self.admin,
        }
        data.update(extra)
        return Assembly.objects.create(**data)

    def make_agreement(self, assembly=None, **extra):
        data = {"assembly": assembly or self.make_assembly(Assembly.Status.IN_PROGRESS), "title": "Pintar fachada"}
        data.update(extra)
        return Agreement.objects.create(**data)


class AssemblyApiTests(CU29BaseTests):
    def payload(self, **extra):
        data = {
            "title": "Asamblea ordinaria", "description": "Presupuesto anual",
            "scheduled_at": (timezone.now() + timedelta(days=10)).isoformat(), "location": "Salón comunal",
        }
        data.update(extra)
        return data

    def test_admin_creates_assembly_scoped_to_tenant_and_audited(self):
        self.as_user(self.admin)
        response = self.client.post(ASSEMBLIES, self.payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        assembly = Assembly.objects.get(pk=response.data["id"])
        self.assertEqual(assembly.condominium_id, self.condo.pk)
        self.assertEqual(assembly.status, Assembly.Status.SCHEDULED)
        self.assertEqual(assembly.created_by_user_id, self.admin.pk)
        self.assertTrue(AuditEvent.objects.filter(action_code="CU29_ASSEMBLY_CREATED", resource_id=str(assembly.pk)).exists())

    def test_cannot_schedule_in_the_past(self):
        self.as_user(self.admin)
        past = (timezone.now() - timedelta(hours=1)).isoformat()
        response = self.client.post(ASSEMBLIES, self.payload(scheduled_at=past), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("scheduled_at", fields(response))

    def test_directiva_reads_but_cannot_write(self):
        assembly = self.make_assembly(status_=Assembly.Status.FINISHED, minutes_text="Acta completa de la reunión")
        self.as_user(self.directiva)
        listing = self.client.get(ASSEMBLIES)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["results"][0]["minutes_text"], "Acta completa de la reunión")
        self.assertEqual(self.client.post(ASSEMBLIES, self.payload(), format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{ASSEMBLIES}{assembly.pk}/", {"title": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{ASSEMBLIES}{assembly.pk}/start/").status_code, 403)

    def test_resident_sees_only_scheduled_assemblies_without_minutes(self):
        scheduled = self.make_assembly(title="Próxima")
        self.make_assembly(status_=Assembly.Status.FINISHED, title="Pasada", minutes_text="Acta secreta de la junta")
        self.make_assembly(status_=Assembly.Status.CANCELLED, title="Cancelada")
        self.as_user(self.resident)
        response = self.client.get(ASSEMBLIES)
        self.assertEqual([row["id"] for row in response.data["results"]], [scheduled.pk])
        self.assertNotIn("minutes_text", response.data["results"][0])
        self.assertEqual(self.client.get(f"{ASSEMBLIES}{scheduled.pk}/").status_code, 200)
        self.assertEqual(self.client.post(ASSEMBLIES, self.payload(), format="json").status_code, 403)

    def test_resident_cannot_open_finished_assembly(self):
        finished = self.make_assembly(status_=Assembly.Status.FINISHED)
        self.as_user(self.resident)
        self.assertEqual(self.client.get(f"{ASSEMBLIES}{finished.pk}/").status_code, 404)

    def test_tenant_isolation(self):
        foreign = self.make_assembly(condo=self.other_condo, title="Ajena")
        self.as_user(self.admin)
        titles = [row["title"] for row in self.client.get(ASSEMBLIES).data["results"]]
        self.assertNotIn("Ajena", titles)
        self.assertEqual(self.client.get(f"{ASSEMBLIES}{foreign.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"{ASSEMBLIES}{foreign.pk}/start/").status_code, 404)

    def test_lifecycle_start_finish_with_minutes(self):
        assembly = self.make_assembly()
        self.as_user(self.admin)
        self.assertEqual(self.client.post(f"{ASSEMBLIES}{assembly.pk}/start/").data["status"], "IN_PROGRESS")
        short = self.client.post(f"{ASSEMBLIES}{assembly.pk}/finish/", {"minutes_text": "corta"}, format="json")
        self.assertEqual(short.status_code, 400)
        done = self.client.post(f"{ASSEMBLIES}{assembly.pk}/finish/", {"minutes_text": "Se aprobó el presupuesto anual."}, format="json")
        self.assertEqual(done.status_code, 200, done.data)
        assembly.refresh_from_db()
        self.assertEqual(assembly.status, Assembly.Status.FINISHED)
        self.assertEqual(assembly.minutes_text, "Se aprobó el presupuesto anual.")

    def test_invalid_transitions_are_rejected(self):
        assembly = self.make_assembly()
        self.as_user(self.admin)
        self.assertEqual(self.client.post(f"{ASSEMBLIES}{assembly.pk}/finish/", {"minutes_text": "Acta de prueba larga"}, format="json").status_code, 400)
        self.client.post(f"{ASSEMBLIES}{assembly.pk}/cancel/", {"reason": "Sin quórum"}, format="json")
        self.assertEqual(self.client.post(f"{ASSEMBLIES}{assembly.pk}/start/").status_code, 400)
        self.assertEqual(self.client.post(f"{ASSEMBLIES}{assembly.pk}/cancel/", format="json").status_code, 400)

    def test_header_editable_only_while_scheduled(self):
        assembly = self.make_assembly()
        self.as_user(self.admin)
        ok = self.client.patch(f"{ASSEMBLIES}{assembly.pk}/", {"location": "Otro salón"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.client.post(f"{ASSEMBLIES}{assembly.pk}/start/")
        blocked = self.client.patch(f"{ASSEMBLIES}{assembly.pk}/", {"location": "Terraza"}, format="json")
        self.assertEqual(blocked.status_code, 400)
        minutes = self.client.patch(f"{ASSEMBLIES}{assembly.pk}/", {"minutes_text": "Borrador del acta"}, format="json")
        self.assertEqual(minutes.status_code, 200)

    def test_minutes_not_allowed_while_scheduled(self):
        assembly = self.make_assembly()
        self.as_user(self.admin)
        response = self.client.patch(f"{ASSEMBLIES}{assembly.pk}/", {"minutes_text": "Antes de tiempo"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_delete_is_not_exposed(self):
        assembly = self.make_assembly()
        self.as_user(self.admin)
        self.assertEqual(self.client.delete(f"{ASSEMBLIES}{assembly.pk}/").status_code, 405)

    def test_status_filter(self):
        self.make_assembly(title="A")
        self.make_assembly(status_=Assembly.Status.FINISHED, title="B")
        self.as_user(self.admin)
        rows = self.client.get(ASSEMBLIES, {"status": "FINISHED"}).data["results"]
        self.assertEqual([row["title"] for row in rows], ["B"])


class AgreementApiTests(CU29BaseTests):
    def payload(self, assembly, **extra):
        data = {
            "assembly": assembly.pk, "title": "Reparar portón", "description": "Cambiar motor",
            "responsible_user": self.directiva.pk, "due_at": (timezone.now() + timedelta(days=15)).isoformat(),
            "estimated_budget": "1500.50",
        }
        data.update(extra)
        return data

    def test_admin_creates_agreement_in_running_assembly(self):
        assembly = self.make_assembly(Assembly.Status.IN_PROGRESS)
        self.as_user(self.admin)
        response = self.client.post(AGREEMENTS, self.payload(assembly), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "PENDING")
        self.assertEqual(response.data["responsible_name"], "Dario Directiva")
        self.assertFalse(response.data["is_overdue"])

    def test_agreement_requires_running_or_finished_assembly(self):
        scheduled = self.make_assembly()
        self.as_user(self.admin)
        response = self.client.post(AGREEMENTS, self.payload(scheduled), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("assembly", fields(response))

    def test_agreement_cannot_use_foreign_assembly_or_responsible(self):
        foreign = self.make_assembly(Assembly.Status.IN_PROGRESS, condo=self.other_condo)
        own = self.make_assembly(Assembly.Status.IN_PROGRESS)
        self.as_user(self.admin)
        self.assertEqual(self.client.post(AGREEMENTS, self.payload(foreign), format="json").status_code, 400)
        outsider = self.client.post(AGREEMENTS, self.payload(own, responsible_user=self.outsider.pk), format="json")
        self.assertEqual(outsider.status_code, 400)
        self.assertIn("responsible_user", fields(outsider))

    def test_budget_and_deadline_validation(self):
        assembly = self.make_assembly(Assembly.Status.IN_PROGRESS)
        self.as_user(self.admin)
        negative = self.client.post(AGREEMENTS, self.payload(assembly, estimated_budget="-1"), format="json")
        self.assertEqual(negative.status_code, 400)
        past = self.client.post(AGREEMENTS, self.payload(assembly, due_at=(timezone.now() - timedelta(days=1)).isoformat()), format="json")
        self.assertEqual(past.status_code, 400)

    def test_directiva_reads_and_cannot_write(self):
        agreement = self.make_agreement()
        self.as_user(self.directiva)
        self.assertEqual(self.client.get(AGREEMENTS).status_code, 200)
        self.assertEqual(self.client.get(f"{AGREEMENTS}{agreement.pk}/").status_code, 200)
        self.assertEqual(self.client.post(AGREEMENTS, self.payload(agreement.assembly), format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{AGREEMENTS}{agreement.pk}/", {"title": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{AGREEMENTS}{agreement.pk}/complete/", format="json").status_code, 403)

    def test_resident_cannot_see_agreements(self):
        agreement = self.make_agreement()
        self.as_user(self.resident)
        self.assertEqual(self.client.get(AGREEMENTS).status_code, 403)
        self.assertEqual(self.client.get(f"{AGREEMENTS}{agreement.pk}/").status_code, 403)

    def test_tenant_isolation(self):
        foreign = self.make_agreement(assembly=self.make_assembly(Assembly.Status.IN_PROGRESS, condo=self.other_condo))
        self.as_user(self.admin)
        self.assertEqual(self.client.get(f"{AGREEMENTS}{foreign.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"{AGREEMENTS}{foreign.pk}/complete/", format="json").status_code, 404)
        self.assertEqual(self.client.get(AGREEMENTS).data["pagination"]["total_items"], 0)

    def test_follow_up_flow_with_cost_and_history(self):
        agreement = self.make_agreement()
        self.as_user(self.admin)
        early_cost = self.client.patch(f"{AGREEMENTS}{agreement.pk}/", {"actual_cost": "10"}, format="json")
        self.assertEqual(early_cost.status_code, 400)
        self.assertEqual(self.client.post(f"{AGREEMENTS}{agreement.pk}/start/", format="json").data["status"], "IN_PROGRESS")
        self.assertEqual(self.client.patch(f"{AGREEMENTS}{agreement.pk}/", {"actual_cost": "800.00"}, format="json").status_code, 200)
        done = self.client.post(f"{AGREEMENTS}{agreement.pk}/complete/", {"actual_cost": "950.25", "comment": "Entregado"}, format="json")
        self.assertEqual(done.status_code, 200, done.data)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, Agreement.Status.COMPLETED)
        self.assertEqual(str(agreement.actual_cost), "950.25")
        self.assertIsNotNone(agreement.completed_at)
        history = self.client.get(f"{AGREEMENTS}{agreement.pk}/history/").data
        codes = [row["action_code"] for row in history]
        self.assertIn("CU29_AGREEMENT_STARTED", codes)
        self.assertIn("CU29_AGREEMENT_COMPLETED", codes)
        self.assertEqual(history[-1]["after_status"], "COMPLETED")
        self.assertEqual(history[-1]["actor_name"], "Ana Admin")

    def test_terminal_agreements_cannot_change(self):
        completed = self.make_agreement(status=Agreement.Status.COMPLETED, completed_at=timezone.now())
        self.as_user(self.admin)
        self.assertEqual(self.client.patch(f"{AGREEMENTS}{completed.pk}/", {"title": "Nuevo"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{AGREEMENTS}{completed.pk}/cancel/", {"reason": "Error"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{AGREEMENTS}{completed.pk}/start/", format="json").status_code, 400)

    def test_cancel_requires_reason(self):
        agreement = self.make_agreement()
        self.as_user(self.admin)
        self.assertEqual(self.client.post(f"{AGREEMENTS}{agreement.pk}/cancel/", {}, format="json").status_code, 400)
        response = self.client.post(f"{AGREEMENTS}{agreement.pk}/cancel/", {"reason": "Ya no aplica"}, format="json")
        self.assertEqual(response.data["status"], "CANCELLED")

    def test_overdue_is_marked_and_deadline_extension_reopens(self):
        agreement = self.make_agreement(status=Agreement.Status.IN_PROGRESS, due_at=timezone.now() - timedelta(days=2))
        self.as_user(self.admin)
        row = self.client.get(f"{AGREEMENTS}{agreement.pk}/").data
        self.assertEqual(row["status"], "OVERDUE")
        self.assertTrue(row["is_overdue"])
        self.assertEqual(self.client.get(AGREEMENTS, {"status": "OVERDUE"}).data["pagination"]["total_items"], 1)
        extended = self.client.patch(
            f"{AGREEMENTS}{agreement.pk}/", {"due_at": (timezone.now() + timedelta(days=5)).isoformat()}, format="json"
        )
        self.assertEqual(extended.status_code, 200, extended.data)
        self.assertEqual(extended.data["status"], "IN_PROGRESS")

    def test_assembly_agreements_listing_and_counters(self):
        assembly = self.make_assembly(Assembly.Status.IN_PROGRESS)
        self.make_agreement(assembly=assembly, title="Uno")
        self.make_agreement(assembly=assembly, title="Dos", status=Agreement.Status.COMPLETED)
        self.as_user(self.directiva)
        rows = self.client.get(f"{ASSEMBLIES}{assembly.pk}/agreements/").data
        self.assertEqual(len(rows), 2)
        detail = self.client.get(f"{ASSEMBLIES}{assembly.pk}/").data
        self.assertEqual(detail["agreements_count"], 2)
        self.assertEqual(detail["open_agreements_count"], 1)
        self.as_user(self.resident)
        self.assertEqual(self.client.get(f"{ASSEMBLIES}{assembly.pk}/agreements/").status_code, 403)

    def test_filter_by_assembly_and_responsible(self):
        first = self.make_assembly(Assembly.Status.IN_PROGRESS)
        second = self.make_assembly(Assembly.Status.IN_PROGRESS)
        self.make_agreement(assembly=first, title="A", responsible_user=self.directiva)
        self.make_agreement(assembly=second, title="B")
        self.as_user(self.admin)
        self.assertEqual(self.client.get(AGREEMENTS, {"assembly": first.pk}).data["pagination"]["total_items"], 1)
        self.assertEqual(self.client.get(AGREEMENTS, {"responsible": self.directiva.pk}).data["pagination"]["total_items"], 1)

    def test_delete_is_not_exposed(self):
        agreement = self.make_agreement()
        self.as_user(self.admin)
        self.assertEqual(self.client.delete(f"{AGREEMENTS}{agreement.pk}/").status_code, 405)

    def test_responsible_options_list_only_active_tenant_members(self):
        self.as_user(self.admin)
        rows = self.client.get(f"{AGREEMENTS}responsibles/").data
        ids = {row["id"] for row in rows}
        self.assertEqual(ids, {self.admin.pk, self.directiva.pk, self.resident.pk})
        self.assertNotIn(self.outsider.pk, ids)
        self.as_user(self.resident)
        self.assertEqual(self.client.get(f"{AGREEMENTS}responsibles/").status_code, 403)


class AgreementAttachmentTests(CU29BaseTests):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="cu29-media-")
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.agreement = self.make_agreement()

    def upload(self, name="acta firmada.pdf", content=b"%PDF-1.4 contenido", **extra):
        return self.client.post(
            f"{AGREEMENTS}{self.agreement.pk}/attachments/",
            {"file": SimpleUploadedFile(name, content), "description": "Acta firmada", **extra},
            format="multipart",
        )

    def test_admin_uploads_lists_downloads_and_deletes(self):
        self.as_user(self.admin)
        created = self.upload()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["file_name"], "acta_firmada.pdf")
        self.assertEqual(created.data["uploaded_by_name"], "Ana Admin")
        stored = AgreementAttachment.objects.get(pk=created.data["id"]).file_path
        self.assertTrue(stored.startswith(f"agreements/{self.condo.pk}/{self.agreement.pk}/"))

        listing = self.client.get(f"{AGREEMENTS}{self.agreement.pk}/attachments/")
        self.assertEqual(len(listing.data), 1)
        self.assertEqual(self.client.get(f"{AGREEMENTS}{self.agreement.pk}/").data["attachments_count"], 1)

        download = self.client.get(created.data["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), b"%PDF-1.4 contenido")

        removed = self.client.delete(f"{AGREEMENTS}{self.agreement.pk}/attachments/{created.data['id']}/")
        self.assertEqual(removed.status_code, 204)
        self.assertFalse(AgreementAttachment.objects.exists())
        self.assertEqual(self.client.get(created.data["download_url"]).status_code, 404)

    def test_directiva_can_download_but_not_upload_or_delete(self):
        self.as_user(self.admin)
        created = self.upload()
        self.as_user(self.directiva)
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.client.get(created.data["download_url"]).status_code, 200)
        self.assertEqual(self.client.delete(f"{AGREEMENTS}{self.agreement.pk}/attachments/{created.data['id']}/").status_code, 403)

    def test_resident_has_no_access(self):
        self.as_user(self.resident)
        self.assertEqual(self.client.get(f"{AGREEMENTS}{self.agreement.pk}/attachments/").status_code, 403)

    def test_rejects_forbidden_extension_and_oversized_files(self):
        self.as_user(self.admin)
        self.assertEqual(self.upload(name="virus.exe", content=b"MZ").status_code, 400)
        with override_settings():
            from paquetes.paquete5_servicios_comunidad.cu29_asambleas_acuerdos import services
            original = services.MAX_ATTACHMENT_BYTES
            services.MAX_ATTACHMENT_BYTES = 5
            try:
                self.assertEqual(self.upload(content=b"123456789").status_code, 400)
            finally:
                services.MAX_ATTACHMENT_BYTES = original

    def test_path_traversal_in_filename_is_neutralised(self):
        self.as_user(self.admin)
        created = self.upload(name="../../etc/passwd.pdf")
        self.assertEqual(created.status_code, 201)
        stored = AgreementAttachment.objects.get(pk=created.data["id"]).file_path
        self.assertNotIn("..", stored)
        self.assertTrue(stored.startswith(f"agreements/{self.condo.pk}/{self.agreement.pk}/"))

    def test_cannot_upload_to_cancelled_agreement(self):
        self.agreement.status = Agreement.Status.CANCELLED
        self.agreement.save()
        self.as_user(self.admin)
        self.assertEqual(self.upload().status_code, 400)

    def test_attachment_of_other_agreement_is_not_reachable(self):
        self.as_user(self.admin)
        created = self.upload()
        other = self.make_agreement(title="Otro acuerdo")
        response = self.client.get(f"{AGREEMENTS}{other.pk}/attachments/{created.data['id']}/download/")
        self.assertEqual(response.status_code, 404)

    def test_foreign_tenant_cannot_reach_attachments(self):
        self.as_user(self.admin)
        created = self.upload()
        self.as_user(self.outsider)
        self.assertEqual(self.client.get(created.data["download_url"]).status_code, 404)
