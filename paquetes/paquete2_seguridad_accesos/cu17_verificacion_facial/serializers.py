from rest_framework import serializers
from security.models import BiometricReference, FaceVerification, AccessEvent
from condominiums.models import Resident, Staff
from accounts.models import User


class ResidentSimpleSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    document_number = serializers.CharField(source="person.document_number", read_only=True)
    document_type = serializers.CharField(source="person.document_type", read_only=True)
    phone = serializers.CharField(source="person.phone", read_only=True)

    class Meta:
        model = Resident
        fields = ("id", "full_name", "document_number", "document_type", "phone", "status")

    def get_full_name(self, obj):
        return f"{obj.person.first_name} {obj.person.last_name}".strip()


class BiometricReferenceSerializer(serializers.ModelSerializer):
    resident_detail = ResidentSimpleSerializer(source="resident", read_only=True)
    enrolled_by_user_email = serializers.CharField(source="enrolled_by_user.email", read_only=True, default="")

    class Meta:
        model = BiometricReference
        fields = (
            "id",
            "resident",
            "resident_detail",
            "reference_image",
            "embedding_dim",
            "model_name",
            "model_version",
            "is_active",
            "enrolled_by_user",
            "enrolled_by_user_email",
            "enrolled_at",
        )
        read_only_fields = (
            "id",
            "embedding_dim",
            "model_name",
            "model_version",
            "is_active",
            "enrolled_by_user",
            "enrolled_at",
        )


class EnrollBiometricReferenceSerializer(serializers.Serializer):
    resident_id = serializers.IntegerField(required=True)
    reference_image = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Imagen base64 principal de referencia",
    )
    images = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Lista de al menos 5 fotografías faciales base64 para entrenamiento del patrón biométrico",
    )

    def validate_resident_id(self, value):
        if not Resident.objects.filter(id=value).exists():
            raise serializers.ValidationError("El residente especificado no existe.")
        return value

    def validate(self, attrs):
        images = attrs.get("images") or []
        ref_img = attrs.get("reference_image")

        if not images and not ref_img:
            raise serializers.ValidationError(
                {"images": "Debe proporcionar al menos 5 fotografías faciales para entrenar el modelo biométrico."}
            )

        if images and len(images) < 5:
            raise serializers.ValidationError(
                {"images": f"Se requieren al menos 5 imágenes faciales para realizar el entrenamiento del modelo (recibidas: {len(images)})."}
            )
        return attrs


class FaceMatchRequestSerializer(serializers.Serializer):
    captured_image = serializers.CharField(required=True, help_text="Fotografía capturada desde la app o cámara en base64 o URL")
    target_resident_id = serializers.IntegerField(required=False, allow_null=True, help_text="Opcional: ID del residente para verificación 1:1")
    threshold = serializers.FloatField(required=False, default=0.70, min_value=0.0, max_value=1.0, help_text="Umbral de coincidencia (defecto 0.70)")


class FaceMatchResultSerializer(serializers.Serializer):
    matched_resident = ResidentSimpleSerializer(read_only=True, allow_null=True)
    biometric_reference_id = serializers.IntegerField(read_only=True, allow_null=True)
    similarity_score = serializers.FloatField(read_only=True)
    threshold = serializers.FloatField(read_only=True)
    result = serializers.ChoiceField(choices=FaceVerification.Result.choices, read_only=True)
    model_name = serializers.CharField(read_only=True)
    model_version = serializers.CharField(read_only=True)


class FaceVerificationConfirmSerializer(serializers.Serializer):
    matched_resident_id = serializers.IntegerField(required=False, allow_null=True)
    biometric_reference_id = serializers.IntegerField(required=False, allow_null=True)
    captured_image = serializers.CharField(required=True)
    similarity_score = serializers.FloatField(required=False, allow_null=True)
    threshold = serializers.FloatField(required=False, allow_null=True, default=0.70)
    result = serializers.ChoiceField(choices=FaceVerification.Result.choices, required=True)
    human_confirmed = serializers.BooleanField(required=True, help_text="Exige confirmación humana (True/False)")
    create_access_event = serializers.BooleanField(required=False, default=True, help_text="Registrar evento de acceso si es confirmado")
    event_type = serializers.ChoiceField(choices=AccessEvent.Type.choices, required=False, default=AccessEvent.Type.ENTRY)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs.get("human_confirmed") is None:
            raise serializers.ValidationError({"human_confirmed": "Debe especificar explícitamente la confirmación humana."})
        return attrs


class FaceVerificationSerializer(serializers.ModelSerializer):
    matched_resident_detail = ResidentSimpleSerializer(source="matched_resident", read_only=True)
    confirmed_by_user_email = serializers.CharField(source="confirmed_by_user.email", read_only=True, default="")
    guard_staff_name = serializers.SerializerMethodField()

    class Meta:
        model = FaceVerification
        fields = (
            "id",
            "captured_image",
            "matched_resident",
            "matched_resident_detail",
            "biometric_reference",
            "guard_staff",
            "guard_staff_name",
            "access_event",
            "similarity_score",
            "threshold",
            "model_name",
            "model_version",
            "result",
            "human_confirmed",
            "confirmed_by_user",
            "confirmed_by_user_email",
            "verified_at",
        )

    def get_guard_staff_name(self, obj):
        if obj.guard_staff and obj.guard_staff.person:
            return f"{obj.guard_staff.person.first_name} {obj.guard_staff.person.last_name}".strip()
        return ""
