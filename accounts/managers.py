from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("El correo electrónico es obligatorio.")
        email = self.normalize_email(email).lower()

        # Pop personal fields to prevent passing them to the User model constructor
        first_name = extra_fields.pop("first_name", None)
        last_name = extra_fields.pop("last_name", None)
        phone = extra_fields.pop("phone", None)

        if "person" not in extra_fields or extra_fields["person"] is None:
            from .models import Person
            person = Person.objects.create(
                first_name=first_name or ("Admin" if extra_fields.get("is_superuser") else "Usuario"),
                last_name=last_name or "Sistema",
                phone=phone or "",
                contact_email=email,
            )
            extra_fields["person"] = person

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superusuario debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superusuario debe tener is_superuser=True.")
        if "role" not in extra_fields or extra_fields["role"] is None:
            from .models import Role

            admin_role = Role.objects.filter(slug="administrador", is_active=True).first()
            if admin_role:
                extra_fields["role"] = admin_role
        return self._create_user(email, password, **extra_fields)
