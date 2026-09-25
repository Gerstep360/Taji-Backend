"""Serializadores para CU08: Registrar y autorizar visitantes."""

from datetime import timedelta
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.models import Person
from condominiums.models import Resident, ResidentUnit, Unit
from security.models import VisitAuthorization


class VisitorPersonSerializer(serializers.ModelSerializer):
    """Representación y lectura de los datos personales del visitante."""

    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Person
        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "document_type",
            "document_number",
            "document_complement",
            "phone",
            "contact_email",
        )


class VisitUnitSummarySerializer(serializers.ModelSerializer):
    """Resumen de la unidad habitacional de destino."""

    sector_name = serializers.CharField(source="sector.name", read_only=True, default="")

    class Meta:
        model = Unit
        fields = ("id", "code", "unit_type", "floor_label", "sector_name")


class VisitResidentSummarySerializer(serializers.ModelSerializer):
    """Resumen del residente autorizante."""

    full_name = serializers.CharField(source="person.full_name", read_only=True)
    document_number = serializers.CharField(source="person.document_number", read_only=True)

    class Meta:
        model = Resident
        fields = ("id", "full_name", "document_number")


class VisitAuthorizationSerializer(serializers.ModelSerializer):
    """
    Serializador principal para CU08 / T020:
    - Lectura completa con objetos anidados (visitante, residente, unidad).
    - Creación y edición atómica con resolución o creación de Person como fuente única.
    - Cumplimiento de integridad transaccional y validaciones de coherencia de negocio.
    """

    # Representación de lectura
    visitor = VisitorPersonSerializer(source="visitor_person", read_only=True)
    resident = VisitResidentSummarySerializer(source="authorized_by_resident", read_only=True)
    unit_detail = VisitUnitSummarySerializer(source="unit", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    # Campos de entrada para el visitante (pueden enviarse anidados o planos)
    visitor_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    visitor_first_name = serializers.CharField(max_length=100, required=False, write_only=True)
    visitor_last_name = serializers.CharField(max_length=120, required=False, write_only=True)
    visitor_document_type = serializers.ChoiceField(
        choices=Person.DocumentType.choices,
        default=Person.DocumentType.CI,
        required=False,
        write_only=True,
    )
    visitor_document_number = serializers.CharField(
        max_length=30, allow_blank=True, required=False, write_only=True
    )
    visitor_document_complement = serializers.CharField(
        max_length=10, allow_blank=True, required=False, write_only=True
    )
    visitor_phone = serializers.CharField(
        max_length=25, allow_blank=True, required=False, write_only=True
    )
    visitor_email = serializers.EmailField(
        allow_blank=True, required=False, write_only=True
    )

    # Entradas de asociación
    unit_id = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.filter(status=Unit.Status.ACTIVE),
        source="unit",
        write_only=True,
    )
    authorized_by_resident_id = serializers.PrimaryKeyRelatedField(
        queryset=Resident.objects.filter(status=Resident.Status.ACTIVE),
        source="authorized_by_resident",
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = VisitAuthorization
        fields = (
            "id",
            "visitor",
            "resident",
            "unit",
            "unit_detail",
            "unit_id",
            "authorized_by_resident_id",
            "purpose",
            "valid_from",
            "valid_until",
            "status",
            "status_display",
            "qr_uuid",
            "qr_expires_at",
            "cancelled_at",
            "notes",
            "created_at",
            # Campos de entrada de visitante
            "visitor_id",
            "visitor_first_name",
            "visitor_last_name",
            "visitor_document_type",
            "visitor_document_number",
            "visitor_document_complement",
            "visitor_phone",
            "visitor_email",
        )
        read_only_fields = (
            "id",
            "unit",
            "status",
            "status_display",
            "qr_uuid",
            "qr_expires_at",
            "cancelled_at",
            "created_at",
        )

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        errors = {}

        # 1. Validar fechas de vigencia
        valid_from = attrs.get("valid_from") or getattr(self.instance, "valid_from", None)
        valid_until = attrs.get("valid_until") or getattr(self.instance, "valid_until", None)

        if valid_from and valid_until:
            if valid_until <= valid_from:
                errors["valid_until"] = ["La fecha de fin debe ser posterior a la fecha de inicio."]
            if not self.instance and valid_until < (timezone.now() - timedelta(minutes=5)):
                errors["valid_until"] = ["El periodo de validez no puede estar en el pasado."]

        # 2. Validar actor, unidad y residente autorizante
        unit = attrs.get("unit") or getattr(self.instance, "unit", None)
        is_admin = bool(user and user.has_system_permission("manage_visits"))

        if not self.instance:  # Creación
            if not is_admin:
                # El actor es un Residente
                resident = getattr(getattr(user, "person", None), "resident", None)
                if not resident or resident.status != Resident.Status.ACTIVE:
                    errors["non_field_errors"] = [
                        "El usuario autenticado no cuenta con un perfil de residente activo."
                    ]
                else:
                    attrs["authorized_by_resident"] = resident
                    # Validar que la unidad esté asociada activamente al residente
                    has_link = ResidentUnit.objects.filter(
                        resident=resident, unit=unit, end_date__isnull=True
                    ).exists()
                    if not has_link:
                        errors["unit_id"] = [
                            "La unidad seleccionada no está asociada activamente al residente."
                        ]
            else:
                # El actor es Administración
                if not attrs.get("authorized_by_resident"):
                    # Si no especifica residente, buscar el residente activo de la unidad
                    active_links = ResidentUnit.objects.filter(
                        unit=unit, end_date__isnull=True, resident__status=Resident.Status.ACTIVE
                    ).select_related("resident")
                    primary_link = active_links.filter(is_primary=True).first() or active_links.first()
                    if primary_link:
                        attrs["authorized_by_resident"] = primary_link.resident
                    else:
                        errors["authorized_by_resident_id"] = [
                            "La unidad no tiene un residente activo asignado. Debe indicar 'authorized_by_resident_id'."
                        ]

        # 3. Validar visitante al crear
        if not self.instance:
            visitor_id = attrs.get("visitor_id")
            first_name = attrs.get("visitor_first_name", "").strip()
            last_name = attrs.get("visitor_last_name", "").strip()

            if not visitor_id:
                if not first_name:
                    errors["visitor_first_name"] = ["El nombre del visitante es obligatorio."]
                if not last_name:
                    errors["visitor_last_name"] = ["El apellido del visitante es obligatorio."]
            else:
                if not Person.objects.filter(id=visitor_id, is_active=True).exists():
                    errors["visitor_id"] = ["El visitante especificado no existe o no está activo."]

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def create(self, validated_data):
        # Extraer campos transitorios de visitante
        visitor_id = validated_data.pop("visitor_id", None)
        first_name = validated_data.pop("visitor_first_name", "").strip()
        last_name = validated_data.pop("visitor_last_name", "").strip()
        doc_type = validated_data.pop("visitor_document_type", Person.DocumentType.CI)
        doc_number = validated_data.pop("visitor_document_number", "").strip() or None
        doc_comp = validated_data.pop("visitor_document_complement", "").strip()
        phone = validated_data.pop("visitor_phone", "").strip()
        email = validated_data.pop("visitor_email", "").strip()

        request = self.context.get("request")
        created_by_user = getattr(request, "user", None) if (request and request.user.is_authenticated) else None

        with transaction.atomic():
            # 1. Obtener o crear Person para el visitante
            if visitor_id:
                visitor_person = Person.objects.select_for_update().get(id=visitor_id)
            elif doc_number:
                # Buscar si ya existe una persona con ese documento para evitar duplicados
                visitor_person = Person.objects.select_for_update().filter(
                    document_type=doc_type,
                    document_number=doc_number,
                    document_complement=doc_comp,
                ).first()

                if visitor_person:
                    # Actualizar datos de contacto si fueron enviados
                    dirty = False
                    if phone and visitor_person.phone != phone:
                        visitor_person.phone = phone
                        dirty = True
                    if email and visitor_person.contact_email != email:
                        visitor_person.contact_email = email
                        dirty = True
                    if dirty:
                        visitor_person.save(update_fields=["phone", "contact_email", "updated_at"])
                else:
                    visitor_person = Person.objects.create(
                        first_name=first_name,
                        last_name=last_name,
                        document_type=doc_type,
                        document_number=doc_number,
                        document_complement=doc_comp,
                        phone=phone,
                        contact_email=email,
                    )
            else:
                visitor_person = Person.objects.create(
                    first_name=first_name,
                    last_name=last_name,
                    document_type=doc_type,
                    document_number=None,
                    phone=phone,
                    contact_email=email,
                )

            # 2. Configurar expiración de QR alineada a la vigencia
            valid_until = validated_data["valid_until"]
            qr_expires_at = validated_data.pop("qr_expires_at", None) or valid_until

            # 3. Crear autorización
            authorization = VisitAuthorization.objects.create(
                visitor_person=visitor_person,
                created_by_user=created_by_user,
                qr_uuid=uuid.uuid4(),
                qr_expires_at=qr_expires_at,
                status=VisitAuthorization.Status.AUTHORIZED,
                **validated_data,
            )

        return authorization

    def update(self, instance, validated_data):
        # Campos permitidos de actualización
        with transaction.atomic():
            for attr in ("purpose", "valid_from", "valid_until", "notes"):
                if attr in validated_data:
                    setattr(instance, attr, validated_data[attr])

            if "valid_until" in validated_data and instance.qr_expires_at > validated_data["valid_until"]:
                instance.qr_expires_at = validated_data["valid_until"]

            instance.save()

        return instance
