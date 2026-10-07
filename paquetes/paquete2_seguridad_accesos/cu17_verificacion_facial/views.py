from django.db import transaction
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from condominiums.models import Resident, Staff
from security.models import BiometricReference, FaceVerification, AccessEvent
from paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.facial_engine import (
    MODEL_NAME,
    MODEL_VERSION,
    EMBEDDING_DIM,
    DEFAULT_THRESHOLD,
    extract_face_embedding,
    process_multi_image_enrollment,
    pack_embedding,
    match_face_against_references,
)
from paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.permissions import CanManageFaceVerification
from paquetes.paquete2_seguridad_accesos.cu17_verificacion_facial.serializers import (
    BiometricReferenceSerializer,
    EnrollBiometricReferenceSerializer,
    FaceMatchRequestSerializer,
    FaceMatchResultSerializer,
    FaceVerificationConfirmSerializer,
    FaceVerificationSerializer,
    ResidentSimpleSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Listar referencias biométricas activas de residentes",
        parameters=[
            OpenApiParameter("resident_id", int, description="Filtrar por residente."),
            OpenApiParameter("is_active", bool, description="Filtrar por estado activo/inactivo."),
            OpenApiParameter("search", str, description="Buscar por nombre o documento del residente."),
        ],
    ),
    retrieve=extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Consultar detalle de referencia biométrica",
    ),
)
@method_decorator(never_cache, name="dispatch")
class BiometricReferenceViewSet(viewsets.ModelViewSet):
    """API para la gestión y versionado de referencias biométricas de residentes (CU17 / RF-17)."""

    serializer_class = BiometricReferenceSerializer
    permission_classes = [IsAuthenticated, CanManageFaceVerification]

    def perform_destroy(self, instance):
        resident = instance.resident
        was_active = instance.is_active
        instance.delete()
        if was_active:
            latest = BiometricReference.objects.filter(resident=resident).order_by("-enrolled_at").first()
            if latest:
                latest.is_active = True
                latest.save(update_fields=["is_active"])

    def get_queryset(self):
        queryset = BiometricReference.objects.select_related("resident__person", "enrolled_by_user")
        resident_id = self.request.query_params.get("resident_id")
        is_active = self.request.query_params.get("is_active")
        search = self.request.query_params.get("search", "").strip()

        if resident_id:
            queryset = queryset.filter(resident_id=resident_id)
        if is_active is not None:
            active_bool = is_active.lower() in ("true", "1")
            queryset = queryset.filter(is_active=active_bool)
        if search:
            queryset = queryset.filter(
                Q(resident__person__first_name__icontains=search)
                | Q(resident__person__last_name__icontains=search)
                | Q(resident__person__document_number__icontains=search)
            )

        return queryset.order_by("-is_active", "-enrolled_at")

    @extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Registrar y versionar referencia biométrica de residente",
        request=EnrollBiometricReferenceSerializer,
        responses={status.HTTP_201_CREATED: BiometricReferenceSerializer},
    )
    @action(detail=False, methods=["post"], url_path="enroll")
    def enroll(self, request):
        serializer = EnrollBiometricReferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resident_id = serializer.validated_data["resident_id"]
        reference_image = serializer.validated_data.get("reference_image") or ""
        images = serializer.validated_data.get("images") or []

        resident = Resident.objects.select_related("person").get(id=resident_id)

        if images:
            enroll_res = process_multi_image_enrollment(images)
            if not enroll_res["success"]:
                return Response(
                    {"error": enroll_res["error"], "detail": enroll_res["message"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            packed_bytes = enroll_res["packed_bytes"]
            primary_img = images[0]
        else:
            extracted = extract_face_embedding(reference_image)
            if not extracted["success"]:
                return Response(
                    {"error": extracted["error"], "detail": extracted["message"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            packed_bytes = pack_embedding(extracted["embedding"])
            primary_img = reference_image

        with transaction.atomic():
            # Desactivar versión anterior activa del residente para mantener historial de versiones
            BiometricReference.objects.filter(resident=resident, is_active=True).update(is_active=False)

            new_ref = BiometricReference.objects.create(
                resident=resident,
                reference_image=primary_img,
                embedding=packed_bytes,
                embedding_dim=EMBEDDING_DIM,
                model_name=MODEL_NAME,
                model_version=MODEL_VERSION,
                is_active=True,
                enrolled_by_user=request.user,
            )

        result_serializer = BiometricReferenceSerializer(new_ref)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Consultar historial de versiones biométricas de un residente",
        responses={status.HTTP_200_OK: BiometricReferenceSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path=r"resident/(?P<resident_id>\d+)/history")
    def resident_history(self, request, resident_id=None):
        references = BiometricReference.objects.filter(resident_id=resident_id).select_related(
            "resident__person", "enrolled_by_user"
        ).order_by("-enrolled_at")
        serializer = BiometricReferenceSerializer(references, many=True)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Listar historial de verificaciones faciales realizadas",
        parameters=[
            OpenApiParameter("result", str, description="Filtrar por resultado (MATCH, NO_MATCH, REVIEW)."),
            OpenApiParameter("human_confirmed", bool, description="Filtrar por confirmación humana."),
            OpenApiParameter("search", str, description="Buscar por nombre o documento del residente."),
        ],
    ),
    retrieve=extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Consultar detalle de una verificación facial",
    ),
)
@method_decorator(never_cache, name="dispatch")
class FaceVerificationViewSet(viewsets.ReadOnlyModelViewSet):
    """API para la verificación facial de residentes y confirmación humana (CU17 / RF-17)."""

    serializer_class = FaceVerificationSerializer
    permission_classes = [IsAuthenticated, CanManageFaceVerification]

    def get_queryset(self):
        queryset = FaceVerification.objects.select_related(
            "matched_resident__person",
            "biometric_reference",
            "guard_staff__person",
            "confirmed_by_user",
            "access_event",
        )
        result_param = self.request.query_params.get("result")
        human_confirmed = self.request.query_params.get("human_confirmed")
        search = self.request.query_params.get("search", "").strip()

        if result_param:
            queryset = queryset.filter(result=result_param.upper())
        if human_confirmed is not None:
            hc_bool = human_confirmed.lower() in ("true", "1")
            queryset = queryset.filter(human_confirmed=hc_bool)
        if search:
            queryset = queryset.filter(
                Q(matched_resident__person__first_name__icontains=search)
                | Q(matched_resident__person__last_name__icontains=search)
                | Q(matched_resident__person__document_number__icontains=search)
            )

        return queryset.order_by("-verified_at")

    @extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Buscar coincidencia facial desde captura fotográfica (1:N o 1:1)",
        request=FaceMatchRequestSerializer,
        responses={status.HTTP_200_OK: FaceMatchResultSerializer},
    )
    @action(detail=False, methods=["post"], url_path="match")
    def match(self, request):
        serializer = FaceMatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        captured_image = serializer.validated_data["captured_image"]
        target_resident_id = serializer.validated_data.get("target_resident_id")
        threshold = serializer.validated_data.get("threshold", DEFAULT_THRESHOLD)

        active_refs = list(
            BiometricReference.objects.filter(is_active=True).select_related("resident__person")
        )

        match_data = match_face_against_references(
            captured_image_b64=captured_image,
            active_references=active_refs,
            target_resident_id=target_resident_id,
            threshold=threshold,
        )

        matched_resident = match_data["matched_resident"]
        biometric_ref = match_data["biometric_reference"]

        guard_staff = Staff.objects.filter(person__user=request.user).first()
        verification = FaceVerification.objects.create(
            captured_image=captured_image,
            matched_resident=matched_resident,
            biometric_reference=biometric_ref,
            guard_staff=guard_staff,
            similarity_score=match_data["similarity_score"],
            threshold=threshold,
            model_name=match_data["model_name"],
            model_version=match_data["model_version"],
            result=match_data["result"],
            human_confirmed=None,
            confirmed_by_user=request.user,
        )

        response_payload = {
            "verification_id": verification.id,
            "matched_resident": ResidentSimpleSerializer(matched_resident).data if matched_resident else None,
            "biometric_reference_id": biometric_ref.id if biometric_ref else None,
            "similarity_score": match_data["similarity_score"],
            "threshold": match_data["threshold"],
            "result": match_data["result"],
            "error_code": match_data.get("error_code"),
            "message": match_data.get("message"),
            "model_name": match_data["model_name"],
            "model_version": match_data["model_version"],
        }

        return Response(response_payload, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Verificación Facial y Biometría (CU17)"],
        summary="Confirmación humana del resultado de verificación facial y registro de acceso",
        request=FaceVerificationConfirmSerializer,
        responses={status.HTTP_201_CREATED: FaceVerificationSerializer},
    )
    @action(detail=False, methods=["post"], url_path="confirm")
    def confirm(self, request):
        serializer = FaceVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        matched_resident_id = serializer.validated_data.get("matched_resident_id")
        biometric_reference_id = serializer.validated_data.get("biometric_reference_id")
        captured_image = serializer.validated_data["captured_image"]
        similarity_score = serializer.validated_data.get("similarity_score")
        threshold = serializer.validated_data.get("threshold", DEFAULT_THRESHOLD)
        result_status = serializer.validated_data["result"]
        human_confirmed = serializer.validated_data["human_confirmed"]
        create_access_event = serializer.validated_data.get("create_access_event", True)
        event_type = serializer.validated_data.get("event_type", AccessEvent.Type.ENTRY)
        notes = serializer.validated_data.get("notes", "")

        matched_resident = Resident.objects.filter(id=matched_resident_id).select_related("person").first() if matched_resident_id else None
        biometric_ref = BiometricReference.objects.filter(id=biometric_reference_id).first() if biometric_reference_id else None

        # Identificar guardia si el usuario autenticado está registrado como Staff
        guard_staff = Staff.objects.filter(person__user=request.user).first()

        with transaction.atomic():
            access_event = None
            if human_confirmed and create_access_event and matched_resident:
                access_event = AccessEvent.objects.create(
                    person=matched_resident.person,
                    guard_staff=guard_staff,
                    event_type=event_type,
                    validation_method=AccessEvent.Method.FACE,
                    validation_result=AccessEvent.Result.APPROVED if result_status in [FaceVerification.Result.MATCH, FaceVerification.Result.REVIEW] else AccessEvent.Result.REJECTED,
                    notes=notes or f"Acceso verificado por reconocimiento facial (Similitud: {similarity_score or 0:.2f})",
                )

            verification = FaceVerification.objects.create(
                captured_image=captured_image,
                matched_resident=matched_resident,
                biometric_reference=biometric_ref,
                guard_staff=guard_staff,
                access_event=access_event,
                similarity_score=similarity_score,
                threshold=threshold,
                model_name=MODEL_NAME,
                model_version=MODEL_VERSION,
                result=result_status,
                human_confirmed=human_confirmed,
                confirmed_by_user=request.user,
            )

        res_serializer = FaceVerificationSerializer(verification)
        return Response(res_serializer.data, status=status.HTTP_201_CREATED)
