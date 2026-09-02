from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .managers import UserManager


class Person(models.Model):
    class DocumentType(models.TextChoices):
        CI = "CI", "Cédula de identidad"
        PASSPORT = "PASSPORT", "Pasaporte"
        OTHER = "OTHER", "Otro"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=120)
    document_type = models.CharField(max_length=20, choices=DocumentType.choices, default=DocumentType.CI)
    document_number = models.CharField(max_length=30, null=True, blank=True)
    document_complement = models.CharField(max_length=10, blank=True)
    phone = models.CharField(max_length=25, blank=True)
    contact_email = models.EmailField(blank=True)
    birth_date = models.DateField(null=True, blank=True)
    profile_photo = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "person"
        ordering = ("last_name", "first_name")
        indexes = [
            models.Index(fields=("last_name",), name="idx_person_last_name"),
            models.Index(fields=("document_number",), name="idx_person_document_number"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(document_number__isnull=True) | ~Q(document_number=""),
                name="chk_person_document",
            ),
            models.UniqueConstraint(
                fields=("document_type", "document_number", "document_complement"),
                condition=Q(document_number__isnull=False),
                name="uq_person_document",
            ),
        ]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name


class SystemPermission(models.Model):
    code = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=240, blank=True)
    module = models.CharField(max_length=60, default="general")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "system_permission"
        ordering = ("code",)
        verbose_name = "permiso del sistema"
        verbose_name_plural = "permisos del sistema"

    def __str__(self):
        return self.name


class Role(models.Model):
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=240, blank=True)
    permissions = models.ManyToManyField(
        SystemPermission,
        blank=True,
        related_name="roles",
        db_table="role_permission",
    )
    is_public = models.BooleanField(default=False, help_text="Puede seleccionarse en un registro público.")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "role"
        ordering = ("name",)
        verbose_name = "rol"
        verbose_name_plural = "roles"

    def __str__(self):
        return self.name


class User(AbstractBaseUser, PermissionsMixin):
    person = models.OneToOneField(
        Person,
        on_delete=models.SET_NULL,
        related_name="user",
        null=True,
        blank=True,
    )
    email = models.EmailField(unique=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    @property
    def first_name(self):
        return self.person.first_name if self.person else ""

    @property
    def last_name(self):
        return self.person.last_name if self.person else ""

    @property
    def phone(self):
        return self.person.phone if self.person else ""


    class Meta:
        db_table = "app_user"
        ordering = ("-date_joined",)
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        indexes = [
            models.Index(fields=("role",), name="idx_app_user_role"),
            models.Index(fields=("is_active",), name="idx_app_user_active"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_superuser=True) | Q(role__isnull=False),
                name="chk_user_role",
            )
        ]

    @property
    def full_name(self):
        return self.person.full_name if self.person else ""

    def has_system_permission(self, code):
        if self.is_superuser:
            return True
        return bool(self.role and self.role.permissions.filter(code=code, is_active=True).exists())

    def __str__(self):
        return self.email


class LoginAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="login_attempts")
    email = models.EmailField(db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    was_successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "login_attempt"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("email", "created_at"), name="idx_login_email_created"),
        ]

    def __str__(self):
        result = "exitoso" if self.was_successful else "fallido"
        return f"{self.email} ({result})"