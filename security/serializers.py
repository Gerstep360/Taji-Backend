"""
Proyecciones de lectura compartidas por los casos de uso de seguridad.

Viven en la app `security` (y no dentro de un CU) porque CU08, CU09 y CU10
necesitan representar al mismo visitante, residente y unidad. Centralizarlas
evita que cada caso de uso redefina los mismos serializadores.
"""

from rest_framework import serializers

from accounts.models import Person
from condominiums.models import Resident, Unit

from .models import VisitAuthorization


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


class VisitAuthorizationSummarySerializer(serializers.ModelSerializer):
    """
    Resumen compacto de una autorización de visita.

    Es lo que consumen el residente al consultar su QR (CU09) y el guardia al
    escanearlo (CU10): identidad del visitante, unidad de destino, unidad
    autorizante y ventana de vigencia.
    """

    visitor = VisitorPersonSerializer(source="visitor_person", read_only=True)
    resident = VisitResidentSummarySerializer(source="authorized_by_resident", read_only=True)
    unit_detail = VisitUnitSummarySerializer(source="unit", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = VisitAuthorization
        fields = (
            "id",
            "status",
            "status_display",
            "purpose",
            "visitor",
            "resident",
            "unit_detail",
            "valid_from",
            "valid_until",
            "qr_uuid",
            "qr_issued_at",
            "qr_expires_at",
        )
        read_only_fields = fields