from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from auditlog.services import record_audit_event
from condominiums.models import Condominium
from paquetes.paquete1_usuarios_condominio.cu03_datos_condominio.serializers import CondominiumSerializer


class CondominiumViewSet(viewsets.ModelViewSet):
    queryset = Condominium.objects.all()
    serializer_class = CondominiumSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get", "put", "patch"], url_path="current")
    def current(self, request):
        condo = Condominium.objects.filter(is_active=True).first()
        
        if not condo and request.method == "GET":
            return Response(
                {"detail": "No hay ningún condominio configurado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.method == "GET":
            serializer = self.get_serializer(condo)
            return Response(serializer.data)

        if request.method in ["PUT", "PATCH"]:
            if not condo:
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                new_condo = serializer.save()
                record_audit_event(
                    action_code="condominium.config.created",
                    resource_type="Condominium",
                    resource_id=new_condo.id,
                    description=f"Condominio configurado: '{new_condo.name}'.",
                    actor_user=request.user,
                    after_data={"name": new_condo.name},
                    request=request,
                )
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            partial = request.method == "PATCH"
            serializer = self.get_serializer(condo, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            updated_condo = serializer.save()
            record_audit_event(
                action_code="condominium.config.updated",
                resource_type="Condominium",
                resource_id=updated_condo.id,
                description=f"Datos del condominio actualizados: '{updated_condo.name}'.",
                actor_user=request.user,
                after_data={"name": updated_condo.name},
                request=request,
            )
            return Response(serializer.data)

