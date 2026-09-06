from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
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
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            partial = request.method == "PATCH"
            serializer = self.get_serializer(condo, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
