from datetime import timedelta
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from condominiums.models import Condominium, Sector, Staff
from maintenance.models import (
    Asset,
    AssetType,
    MaintenancePlan,
    Supplier,
    WorkOrder,
    WorkOrderAssignment,
)
from tenancy.models import TenantMembership


class CU25WorkOrderApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manage_permission, _ = SystemPermission.objects.get_or_create(
            code="manage_maintenance", defaults={"name": "Gestionar mantenimiento"}
        )
        cls.view_permission, _ = SystemPermission.objects.get_or_create(
            code="view_assigned_work_orders", defaults={"name": "Ver trabajos asignados"}
        )
        cls.status_permission, _ = SystemPermission.objects.get_or_create(
            code="update_work_order_status", defaults={"name": "Actualizar estado"}
        )
        cls.evidence_permission, _ = SystemPermission.objects.get_or_create(
            code="attach_work_evidence", defaults={"name": "Adjuntar evidencias"}
        )
        cls.admin_role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador"}
        )
        cls.admin_role.permissions.add(cls.manage_permission)
        cls.maintenance_role, _ = Role.objects.get_or_create(
            slug="mantenimiento", defaults={"name": "Mantenimiento"}
        )
        cls.maintenance_role.permissions.add(
            cls.view_permission, cls.status_permission, cls.evidence_permission
        )
        cls.resident_role, _ = Role.objects.get_or_create(
            slug="residente", defaults={"name": "Residente"}
        )

        cls.condo = Condominium.objects.create(name="Condominio CU25")
        cls.other_condo = Condominium.objects.create(name="Otro condominio CU25")
        cls.sector = Sector.objects.create(
            condominium=cls.condo, code="A", name="Bloque A"
        )
        cls.other_sector = Sector.objects.create(
            condominium=cls.other_condo, code="B", name="Bloque B"
        )
        cls.asset_type = AssetType.objects.create(code="BOMB-CU25", name="Bomba CU25")
        cls.asset = Asset.objects.create(
            asset_type=cls.asset_type,
            sector=cls.sector,
            code="BOM-001-CU25",
            name="Bomba de agua",
        )
        cls.other_asset = Asset.objects.create(
            asset_type=cls.asset_type,
            sector=cls.other_sector,
            code="BOM-002-CU25",
            name="Bomba de otro condominio",
        )

        cls.admin = cls._make_user("admin-cu25@example.test", "CU25 Admin", cls.admin_role)
        cls.worker = cls._make_user(
            "worker-cu25@example.test", "CU25 Técnico", cls.maintenance_role
        )
        cls.resident = cls._make_user(
            "resident-cu25@example.test", "CU25 Residente", cls.resident_role
        )
        cls.staff = Staff.objects.create(
            person=cls.worker.person,
            condominium=cls.condo,
            employee_code="MNT-CU25",
            staff_type=Staff.Type.MAINTENANCE,
            status=Staff.Status.ACTIVE,
        )
        for user in (cls.admin, cls.worker, cls.resident):
            TenantMembership.objects.create(
                user=user,
                condominium=cls.condo,
                role=user.role,
                is_default=True,
            )

    @staticmethod
    def _make_user(email, name, role):
        first, last = name.split(" ", 1)
        person = Person.objects.create(
            first_name=first,
            last_name=last,
            document_type=Person.DocumentType.CI,
            document_number=f"CU25-{email.split('@')[0]}",
        )
        return User.objects.create_user(
            email=email,
            password="SecurePassword-123!",
            person=person,
            role=role,
            is_approved=True,
        )

    def _create_order(self, user=None, asset=None, **extra):
        self.client.force_authenticate(user=user or self.admin)
        payload = {
            "asset_id": (asset or self.asset).pk,
            "work_type": WorkOrder.Type.CORRECTIVE,
            "title": "Revisar bomba",
            "description": "Revisar presión y válvulas.",
            **extra,
        }
        return self.client.post(
            reverse("maintenance-work-order-list"), payload, format="json"
        )

    def test_manager_creates_tenant_scoped_order_and_initial_history(self):
        response = self._create_order()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = WorkOrder.objects.get(pk=response.data["id"])
        self.assertEqual(order.condominium_id, self.condo.pk)
        self.assertEqual(order.created_by_user_id, self.admin.pk)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.status_history.count(), 1)
        self.assertTrue(response.data["public_code"].startswith("OT-"))

    def test_manager_cannot_create_order_from_another_tenant_asset(self):
        response = self._create_order(asset=self.other_asset)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("asset_id", response.data["error"]["fields"])

    def test_order_list_never_returns_another_tenants_work(self):
        own = WorkOrder.objects.create(
            condominium=self.condo,
            public_code="OT-CU25-OWN",
            asset=self.asset,
            work_type=WorkOrder.Type.INSPECTION,
            title="Propia",
        )
        WorkOrder.objects.create(
            condominium=self.other_condo,
            public_code="OT-CU25-OTHER",
            asset=self.other_asset,
            work_type=WorkOrder.Type.INSPECTION,
            title="Ajena",
        )
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(reverse("maintenance-work-order-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {
            item["id"]
            for item in response.data.get("results", response.data)
        }
        self.assertIn(own.pk, ids)
        self.assertEqual(len(ids), 1)

    def test_assigning_work_order_records_assignment_and_status_history(self):
        response = self._create_order()
        order_id = response.data["id"]
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            reverse("maintenance-work-order-assign", args=(order_id,)),
            {"staff_id": self.staff.pk, "reason": "Turno de mantenimiento"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], WorkOrder.Status.ASSIGNED)
        self.assertEqual(response.data["current_assignee_staff_id"], self.staff.pk)
        self.assertEqual(WorkOrderAssignment.objects.filter(work_order_id=order_id).count(), 1)
        self.assertEqual(response.data["status_history"][-1]["to_status"], WorkOrder.Status.ASSIGNED)

    def test_assigned_worker_can_progress_and_complete_order(self):
        created = self._create_order()
        order_id = created.data["id"]
        WorkOrder.objects.filter(pk=order_id).update(
            current_assignee_staff=self.staff,
            status=WorkOrder.Status.ASSIGNED,
        )
        self.client.force_authenticate(user=self.worker)

        started = self.client.post(
            reverse("maintenance-work-order-change-status", args=(order_id,)),
            {"status": WorkOrder.Status.IN_PROGRESS},
            format="json",
        )
        self.assertEqual(started.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(started.data["started_at"])

        completed = self.client.post(
            reverse("maintenance-work-order-change-status", args=(order_id,)),
            {"status": WorkOrder.Status.COMPLETED, "notes": "Trabajo verificado."},
            format="json",
        )

        self.assertEqual(completed.status_code, status.HTTP_200_OK)
        self.assertEqual(completed.data["status"], WorkOrder.Status.COMPLETED)
        self.assertIsNotNone(completed.data["completed_at"])

    def test_maintenance_plan_due_date_advances_when_order_is_completed(self):
        plan = MaintenancePlan.objects.create(
            asset=self.asset,
            name="Plan mensual",
            frequency_days=30,
            next_due_at=timezone.now(),
        )
        created = self._create_order(
            maintenance_plan_id=plan.pk,
            scheduled_for=timezone.now().isoformat(),
        )
        order_id = created.data["id"]
        WorkOrder.objects.filter(pk=order_id).update(
            current_assignee_staff=self.staff,
            status=WorkOrder.Status.ASSIGNED,
        )
        self.client.force_authenticate(user=self.worker)

        self.client.post(
            reverse("maintenance-work-order-change-status", args=(order_id,)),
            {"status": WorkOrder.Status.IN_PROGRESS},
            format="json",
        )
        response = self.client.post(
            reverse("maintenance-work-order-change-status", args=(order_id,)),
            {"status": WorkOrder.Status.COMPLETED},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        plan.refresh_from_db()
        self.assertIsNotNone(plan.last_completed_at)
        self.assertGreaterEqual(
            plan.next_due_at,
            plan.last_completed_at + timedelta(days=30),
        )

    def test_manager_creates_tenant_scoped_supplier(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            reverse("maintenance-supplier-list"),
            {
                "name": "Servicios CU25",
                "email": "proveedor-cu25@example.test",
                "specialty": "Bombas",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        supplier = Supplier.objects.get(pk=response.data["id"])
        self.assertEqual(supplier.condominium_id, self.condo.pk)

    def test_manager_cannot_create_plan_for_another_tenant_asset(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            reverse("maintenance-plan-list"),
            {
                "asset_id": self.other_asset.pk,
                "name": "Plan ajeno",
                "frequency_days": 30,
                "next_due_at": timezone.now().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("asset_id", response.data["error"]["fields"])

    def test_cost_items_recalculate_actual_cost(self):
        created = self._create_order()
        order_id = created.data["id"]
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            reverse("maintenance-work-order-add-cost-item", args=(order_id,)),
            {
                "description": "Repuesto",
                "quantity": "2",
                "unit_cost": "15.50",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["actual_cost"], "31.00")
        cost_item_id = response.data["cost_items"][0]["id"]

        response = self.client.delete(
            reverse(
                "maintenance-work-order-delete-cost-item",
                args=(order_id, cost_item_id),
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["actual_cost"])
        self.assertEqual(response.data["cost_items"], [])

    def test_assigned_worker_cannot_skip_status_transition(self):
        created = self._create_order()
        order_id = created.data["id"]
        WorkOrder.objects.filter(pk=order_id).update(
            current_assignee_staff=self.staff,
            status=WorkOrder.Status.ASSIGNED,
        )
        self.client.force_authenticate(user=self.worker)

        response = self.client.post(
            reverse("maintenance-work-order-change-status", args=(order_id,)),
            {"status": WorkOrder.Status.COMPLETED},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            WorkOrder.objects.get(pk=order_id).status,
            WorkOrder.Status.ASSIGNED,
        )

    def test_assigned_worker_can_upload_evidence(self):
        created = self._create_order()
        order_id = created.data["id"]
        WorkOrder.objects.filter(pk=order_id).update(
            current_assignee_staff=self.staff,
            status=WorkOrder.Status.ASSIGNED,
        )
        self.client.force_authenticate(user=self.worker)

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse(
                        "maintenance-work-order-add-attachment",
                        args=(order_id,),
                    ),
                    {
                        "file": SimpleUploadedFile(
                            "bomba.jpg",
                            b"maintenance evidence",
                            content_type="image/jpeg",
                        ),
                        "caption": "Sello desgastado",
                    },
                    format="multipart",
                )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["attachments"]), 1)
        self.assertEqual(
            response.data["attachments"][0]["caption"],
            "Sello desgastado",
        )

    def test_resident_without_maintenance_permissions_is_denied(self):
        self.client.force_authenticate(user=self.resident)

        response = self.client.get(reverse("maintenance-work-order-list"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
