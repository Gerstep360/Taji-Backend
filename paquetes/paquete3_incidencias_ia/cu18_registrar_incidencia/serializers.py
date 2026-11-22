"""Serializadores para CU18: Registrar incidencia."""

from rest_framework import serializers

from condominiums.models import Sector, Unit
from incidents.models import Incident, IncidentAttachment, IncidentCategory, PriorityLevel
from maintenance.models import Asset

from . import services


class PriorityLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriorityLevel
        fields = ("id", "code", "name", "rank", "target_minutes")


class IncidentCategorySerializer(serializers.ModelSerializer):
    default_priority = serializers.SerializerMethodField()

    class Meta:
        model = IncidentCategory
        fields = ("id", "code", "name", "description", "default_priority")

    def get_default_priority(self, category) -> dict | None:
        priority = services.resolve_initial_priority(category)
        return {"code": priority.code, "name": priority.name} if priority else None


class SectorOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sector
        fields = ("id", "code", "name", "sector_type", "parent")


class UnitOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ("id", "code", "unit_type", "sector")


class AssetOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = ("id", "code", "name", "sector")


class IncidentEvidenceSerializer(serializers.ModelSerializer):
    file_name = serializers.SerializerMethodField()

    class Meta:
        model = IncidentAttachment
        fields = ("id", "file_type", "file_name", "created_at")

    def get_file_name(self, attachment) -> str:
        return services.storage_file_name(attachment.file_path)


class IncidentSerializer(serializers.ModelSerializer):
    """Representación de la incidencia recién registrada (respuesta de confirmación)."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    reporter = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    priority = serializers.SerializerMethodField()
    sector = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()
    asset = serializers.SerializerMethodField()
    evidences = IncidentEvidenceSerializer(source="attachments", many=True, read_only=True)

    class Meta:
        model = Incident
        fields = (
            "id", "public_code", "condominium", "status", "status_display", "title", "description",
            "category", "priority", "sector", "unit", "asset", "reporter", "evidences",
            "created_at", "updated_at",
        )

    def get_reporter(self, incident) -> dict | None:
        user = incident.reporter_user
        return {"id": user.pk, "full_name": user.full_name or user.email} if user else None

    def get_category(self, incident) -> dict | None:
        item = incident.category
        return {"id": item.pk, "code": item.code, "name": item.name} if item else None

    def get_priority(self, incident) -> dict | None:
        item = incident.priority
        return {"id": item.pk, "code": item.code, "name": item.name, "rank": item.rank} if item else None

    def get_sector(self, incident) -> dict | None:
        item = incident.sector
        return {"id": item.pk, "code": item.code, "name": item.name} if item else None

    def get_unit(self, incident) -> dict | None:
        item = incident.unit
        return {"id": item.pk, "code": item.code} if item else None

    def get_asset(self, incident) -> dict | None:
        item = incident.asset
        return {"id": item.pk, "code": item.code, "name": item.name} if item else None


class IncidentCreateSerializer(serializers.Serializer):
    """
    Entrada de CU18 / T032-T033. Solo acepta datos que el usuario puede decidir.
    Condominio, reportante, código, estado, prioridad y fechas los fija el servidor;
    cualquier valor enviado para ellos se ignora.
    Contexto requerido: `condominium`, `request`, `full_unit_scope`.
    """

    title = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    description = serializers.CharField(
        max_length=5000,
        error_messages={
            "required": "La descripción es obligatoria.",
            "blank": "La descripción no puede estar vacía.",
        },
    )
    category = serializers.PrimaryKeyRelatedField(
        queryset=IncidentCategory.objects.filter(is_active=True),
        error_messages={
            "required": "La categoría es obligatoria.",
            "does_not_exist": "La categoría no existe o no está activa.",
            "incorrect_type": "La categoría no es válida.",
        },
    )
    sector = serializers.PrimaryKeyRelatedField(
        queryset=Sector.objects.none(),
        error_messages={
            "required": "La ubicación (sector) es obligatoria.",
            "null": "La ubicación (sector) es obligatoria.",
            "does_not_exist": "La ubicación no existe o no pertenece a tu condominio.",
            "incorrect_type": "La ubicación no es válida.",
        },
    )
    unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.none(),
        required=False,
        allow_null=True,
        error_messages={
            "does_not_exist": "La unidad no existe o no estás autorizado a vincularla.",
            "incorrect_type": "La unidad no es válida.",
        },
    )
    asset = serializers.PrimaryKeyRelatedField(
        queryset=Asset.objects.none(),
        required=False,
        allow_null=True,
        error_messages={
            "does_not_exist": "El activo no existe o no pertenece a tu condominio.",
            "incorrect_type": "El activo no es válido.",
        },
    )
    evidences = serializers.ListField(
        child=serializers.FileField(allow_empty_file=True, use_url=False),
        required=False,
        allow_empty=True,
        write_only=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        condominium = self.context.get("condominium")
        request = self.context.get("request")
        if condominium is None or request is None:
            return
        self.fields["sector"].queryset = services.tenant_sectors(condominium)
        self.fields["unit"].queryset = services.selectable_units(
            condominium, request.user, self.context.get("full_unit_scope", False)
        )
        self.fields["asset"].queryset = services.tenant_assets(condominium)

    def validate_evidences(self, files):
        max_files = services.evidence_limits()["max_files"]
        if len(files) > max_files:
            raise serializers.ValidationError(f"Puedes adjuntar como máximo {max_files} archivos.")
        validated, errors = [], []
        for upload in files:
            evidence, error = services.validate_evidence(upload)
            if error:
                errors.append(error)
            else:
                validated.append(evidence)
        if errors:
            raise serializers.ValidationError(errors)
        return validated

    def validate(self, attrs):
        unit = attrs.get("unit")
        if unit is not None and not services.sector_contains(attrs["sector"], unit.sector):
            raise serializers.ValidationError({"unit": "La unidad no pertenece a la ubicación seleccionada."})
        return attrs
