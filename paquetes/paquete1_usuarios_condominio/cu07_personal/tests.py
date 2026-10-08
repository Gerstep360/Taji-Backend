from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Person, Role, SystemPermission, User
from condominiums.models import Condominium, Staff
from tenancy.models import TenantMembership
from security.models import SecurityShift




class CU07StaffSystemAccessTests(APITestCase):
    def setUp(self):
        # Create permissions and admin role
        self.perm_manage_staff, _ = SystemPermission.objects.get_or_create(
            code="manage_staff", defaults={"name": "Gestionar personal", "module": "staff"}
        )
        self.admin_role, _ = Role.objects.get_or_create(
            slug="administrador", defaults={"name": "Administrador", "is_active": True}
        )
        self.admin_role.permissions.add(self.perm_manage_staff)

        # Create security role
        self.perm_use_cu13, _ = SystemPermission.objects.get_or_create(
            code="shift_execution", defaults={"name": "Ejecutar turnos", "module": "security"}
        )
        self.security_role, _ = Role.objects.get_or_create(
            slug="seguridad", defaults={"name": "Seguridad", "is_active": True}
        )
        self.security_role.permissions.add(self.perm_use_cu13)

        # Create admin user
        self.admin_person = Person.objects.create(
            first_name="Admin", last_name="System", contact_email="admin@taji.com"
        )
        self.admin_user = User.objects.create_user(
            email="admin@taji.com",
            password="AdminPassword123!",
            person=self.admin_person,
            role=self.admin_role,
            is_approved=True,
            is_staff=True,
        )


        self.client.force_authenticate(user=self.admin_user)
        self.list_url = reverse("staff-list")

    def test_01_create_staff_without_access(self):
        payload = {
            "first_name": "Juan",
            "last_name": "Perez",
            "document_type": "CI",
            "document_number": "123456",
            "staff_type": "SECURITY",
            "status": "ACTIVE",
            "create_system_access": False,
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertFalse(res.data["has_system_access"])
        self.assertIsNone(res.data["user_id"])
        staff = Staff.objects.get(pk=res.data["id"])
        self.assertFalse(hasattr(staff.person, "user") and staff.person.user is not None)

    def test_02_create_security_staff_with_access(self):
        payload = {
            "first_name": "Pepo",
            "last_name": "Juan",
            "document_type": "CI",
            "document_number": "654321",
            "contact_email": "pepe@taji.com",
            "staff_type": "SECURITY",
            "status": "ACTIVE",
            "create_system_access": True,
            "access_email": "pepe@taji.com",
            "password": "SecureGuardPassword123!",
            "password_confirm": "SecureGuardPassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["has_system_access"])
        self.assertEqual(res.data["role_slug"], "seguridad")

        staff = Staff.objects.get(pk=res.data["id"])
        user = staff.person.user
        self.assertIsNotNone(user)
        self.assertEqual(user.email, "pepe@taji.com")
        self.assertEqual(user.role.slug, "seguridad")
        self.assertEqual(user.person, staff.person)

    def test_03_user_has_security_role(self):
        payload = {
            "first_name": "Carlos",
            "last_name": "Guardia",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "carlos@taji.com",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="carlos@taji.com")
        self.assertEqual(user.role.slug, "seguridad")

    def test_04_user_person_is_same_as_staff_person(self):
        payload = {
            "first_name": "Pedro",
            "last_name": "Lopez",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "pedro@taji.com",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        staff = Staff.objects.get(pk=res.data["id"])
        self.assertEqual(staff.person.user.person_id, staff.person_id)

    def test_05_06_07_no_duplicate_person_staff_user(self):
        payload = {
            "first_name": "Ana",
            "last_name": "Gomez",
            "document_type": "CI",
            "document_number": "999888",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "ana@taji.com",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Person.objects.filter(document_number="999888").count(), 1)
        self.assertEqual(Staff.objects.filter(person__document_number="999888").count(), 1)
        self.assertEqual(User.objects.filter(email="ana@taji.com").count(), 1)

    def get_error_fields(self, res):
        if isinstance(res.data, dict):
            if "fields" in res.data:
                return res.data["fields"]
            if "error" in res.data and isinstance(res.data["error"], dict) and "fields" in res.data["error"]:
                return res.data["error"]["fields"]
        return res.data

    def test_08_duplicate_email_of_another_person_fails(self):
        payload = {
            "first_name": "Maria",
            "last_name": "Suarez",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "admin@taji.com",  # Already belongs to admin_person
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("access_email", self.get_error_fields(res))

    def test_09_10_password_validation_and_mismatch(self):
        payload_mismatch = {
            "first_name": "Luis",
            "last_name": "Mora",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "luis@taji.com",
            "password": "SecurePassword123!",
            "password_confirm": "DifferentPassword123!",
        }
        res = self.client.post(self.list_url, payload_mismatch, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirm", self.get_error_fields(res))

    def test_11_password_is_saved_hashed(self):
        payload = {
            "first_name": "Diego",
            "last_name": "Torres",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "diego@taji.com",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="diego@taji.com")
        self.assertNotEqual(user.password, "SecurePassword123!")
        self.assertTrue(user.check_password("SecurePassword123!"))

    def test_12_13_enable_access_for_existing_staff(self):
        # Create without access first
        staff = Staff.objects.create(
            person=Person.objects.create(first_name="Ramiro", last_name="Vargas", contact_email="ramiro@taji.com"),
            staff_type=Staff.Type.SECURITY,
            status=Staff.Status.ACTIVE,
        )
        url = reverse("staff-detail", kwargs={"pk": staff.pk})

        payload = {
            "create_system_access": True,
            "access_email": "ramiro@taji.com",
            "password": "NewSecurePassword123!",
            "password_confirm": "NewSecurePassword123!",
        }
        res = self.client.patch(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["has_system_access"])

        # Second update does not duplicate user
        res2 = self.client.patch(url, {"notes": "Nota actualizada"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(email="ramiro@taji.com").count(), 1)

    def test_14_reset_password(self):
        payload = {
            "first_name": "Hugo",
            "last_name": "Rios",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "hugo@taji.com",
            "password": "OldPassword123!",
            "password_confirm": "OldPassword123!",
        }
        create_res = self.client.post(self.list_url, payload, format="json")
        staff_id = create_res.data["id"]

        reset_url = reverse("staff-reset-password", kwargs={"pk": staff_id})
        reset_res = self.client.post(
            reset_url,
            {"password": "BrandNewPassword123!", "password_confirm": "BrandNewPassword123!"},
            format="json",
        )
        self.assertEqual(reset_res.status_code, status.HTTP_200_OK)

        user = User.objects.get(email="hugo@taji.com")
        self.assertTrue(user.check_password("BrandNewPassword123!"))

    def test_15_toggle_access_activation(self):
        payload = {
            "first_name": "Oscar",
            "last_name": "Blanco",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "oscar@taji.com",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        staff_id = res.data["id"]

        url = reverse("staff-detail", kwargs={"pk": staff_id})
        # Deactivate
        self.client.patch(url, {"toggle_access": False}, format="json")
        user = User.objects.get(email="oscar@taji.com")
        self.assertFalse(user.is_active)

        # Reactivate
        self.client.patch(url, {"toggle_access": True}, format="json")
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_16_permission_required(self):
        non_admin_role, _ = Role.objects.get_or_create(
            slug="mantenimiento", defaults={"name": "Mantenimiento", "is_active": True}
        )
        non_admin_person = Person.objects.create(first_name="Plain", last_name="User")
        plain_user = User.objects.create_user(
            email="plain@taji.com", password="Password123!", person=non_admin_person, role=non_admin_role
        )
        self.client.force_authenticate(user=plain_user)

        res = self.client.post(
            self.list_url,
            {
                "first_name": "Test",
                "last_name": "Forbidden",
                "staff_type": "SECURITY",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


    def test_17_18_security_user_can_authenticate_and_access_cu13(self):
        condo = Condominium.objects.create(name="Condominio del administrador")
        TenantMembership.objects.create(user=self.admin_user, condominium=condo,
            role=self.admin_role, is_default=True)
        payload = {
            "first_name": "Guardia",
            "last_name": "Ejecutor",
            "staff_type": "SECURITY",
            "create_system_access": True,
            "access_email": "guardia@taji.com",
            "password": "GuardiaPassword123!",
            "password_confirm": "GuardiaPassword123!",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        guard_user = User.objects.get(email="guardia@taji.com")
        self.assertTrue(guard_user.check_password("GuardiaPassword123!"))
        self.assertEqual(Staff.objects.get(person=guard_user.person).condominium_id, condo.pk)
        membership = TenantMembership.objects.get(user=guard_user, condominium=condo)
        self.assertEqual(membership.role, self.security_role)
        self.assertTrue(membership.is_active)

        # Authenticate as guard and call CU13 endpoint
        self.client.force_authenticate(user=guard_user)
        cu13_url = reverse("turnos-seguridad-list")
        cu13_res = self.client.get(cu13_url)
        self.assertEqual(cu13_res.status_code, status.HTTP_200_OK)

