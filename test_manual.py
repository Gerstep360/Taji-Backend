"""
Script de pruebas manuales para CU19 (T034, T037, T038)
Simula peticiones HTTP al backend usando REST Framework APIClient.
Uso: python test_manual.py
"""
import os
import sys
import django

# 1. Configurar entorno Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import User, Role, Person
from condominiums.models import Condominium, Resident, Staff
from incidents.models import (
    Incident,
    IncidentCategory,
    PriorityLevel,
    IncidentStatusHistory,
    IncidentComment,
)

def run_tests():
    print("============================================================")
    print(" INICIO DE PRUEBAS MANUALES CU19 (T034, T037, T038) ")
    print("============================================================")

    client = APIClient()

    # 1. Obtener o crear datos base para las pruebas
    condo, _ = Condominium.objects.get_or_create(name="Condominio Test CU19")
    
    admin_role, _ = Role.objects.get_or_create(slug="administrador", defaults={"name": "Administrador"})
    staff_role, _ = Role.objects.get_or_create(slug="mantenimiento", defaults={"name": "Mantenimiento"})
    resident_role, _ = Role.objects.get_or_create(slug="residente", defaults={"name": "Residente"})

    admin_person, _ = Person.objects.get_or_create(document_number="DOCADMIN19", defaults={"first_name": "Admin", "last_name": "CU19"})
    admin_user, _ = User.objects.get_or_create(
        email="admin19@taji.test",
        defaults={"person": admin_person, "role": admin_role, "is_approved": True}
    )
    admin_user.set_password("Test1234!")
    admin_user.save()

    resident_person, _ = Person.objects.get_or_create(document_number="DOCRES19", defaults={"first_name": "Residente", "last_name": "CU19"})
    resident_user, _ = User.objects.get_or_create(
        email="residente19@taji.test",
        defaults={"person": resident_person, "role": resident_role, "is_approved": True}
    )
    resident_user.set_password("Test1234!")
    resident_user.save()

    staff_person, _ = Person.objects.get_or_create(document_number="DOCSTAFF19", defaults={"first_name": "Staff", "last_name": "CU19"})
    staff_user, _ = User.objects.get_or_create(
        email="staff19@taji.test",
        defaults={"person": staff_person, "role": staff_role, "is_approved": True}
    )
    staff_user.set_password("Test1234!")
    staff_user.save()

    staff_obj, _ = Staff.objects.get_or_create(
        person=staff_person,
        condominium=condo,
        defaults={"staff_type": "MAINTENANCE", "status": Staff.Status.ACTIVE}
    )

    priority_high, _ = PriorityLevel.objects.get_or_create(
        code="HIGH",
        defaults={"name": "Alta", "rank": 3, "target_minutes": 120, "is_active": True}
    )
    category, _ = IncidentCategory.objects.get_or_create(
        code="CAT_CU19",
        defaults={"name": "Categoría CU19", "is_active": True}
    )

    # Crear incidencia de prueba
    incident = Incident.objects.create(
        reporter_user=resident_user,
        category=category,
        priority=priority_high,
        title="Incidencia Manual CU19",
        description="Prueba automatizada local para CU19",
        status=Incident.Status.REPORTED,
        due_at=timezone.now() - timedelta(hours=1) # Vencida para probar T038
    )
    code = incident.public_code
    print(f"[+] Incidencia creada con código público: {code}")

    passed = 0
    failed = 0

    def test_case(name, func):
        nonlocal passed, failed
        print(f"\n[EJECUTANDO] {name}...")
        try:
            func()
            print(f"[ÉXITO] {name}")
            passed += 1
        except Exception as e:
            print(f"[FALLÓ] {name} -> Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    # -------------------------------------------------------------------------
    # T038: Filtros de SLA, tablero y fecha objetivo
    # -------------------------------------------------------------------------
    def test_t038_sla_and_board():
        client.force_authenticate(user=admin_user)
        
        # 1. Listar con filtro is_pending
        resp = client.get("/api/v1/paquete3/incidents/", {"is_pending": "true"})
        assert resp.status_code == status.HTTP_200_OK, f"Status code incorrecto: {resp.status_code}"
        
        # 2. Listar con filtro sla_status=overdue
        resp = client.get("/api/v1/paquete3/incidents/", {"sla_status": "overdue"})
        assert resp.status_code == status.HTTP_200_OK, f"Status code incorrecto: {resp.status_code}"
        
        # 3. Tablero summary
        resp = client.get("/api/v1/paquete3/incidents/board-summary/")
        assert resp.status_code == status.HTTP_200_OK, f"Status code incorrecto: {resp.status_code}"
        assert "overdue_count" in resp.data, "Falta overdue_count en board-summary"

        # 4. Establecer fecha objetivo (set-target-date)
        resp = client.post(f"/api/v1/paquete3/incidents/{code}/set-target-date/", {"target_minutes": 240}, format="json")
        assert resp.status_code == status.HTTP_200_OK, f"No se pudo establecer fecha objetivo: {resp.status_code} - {resp.data}"

    test_case("T038: Filtros de SLA, Tablero y Fecha Objetivo", test_t038_sla_and_board)

    # -------------------------------------------------------------------------
    # T034: Cambio de estado e historial de incidencias
    # -------------------------------------------------------------------------
    def test_t034_status_and_history():
        client.force_authenticate(user=admin_user)

        # 1. Cambiar estado a IN_PROGRESS
        resp = client.post(f"/api/v1/paquete3/incidents/{code}/change-status/", {"status": "IN_PROGRESS", "comment": "Iniciando trabajo"}, format="json")
        assert resp.status_code == status.HTTP_200_OK, f"Error cambiando estado a IN_PROGRESS: {resp.status_code} - {resp.data}"

        # 2. Consultar historial de estados (/history/)
        resp = client.get(f"/api/v1/paquete3/incidents/{code}/history/")
        assert resp.status_code == status.HTTP_200_OK, f"Error consultando historial: {resp.status_code}"
        assert isinstance(resp.data, list), "El historial debe ser una lista"
        assert len(resp.data) >= 1, "Debe haber al menos un registro en el historial"

        # 3. Cambiar a estado RESOLVED
        resp = client.post(f"/api/v1/paquete3/incidents/{code}/change-status/", {"status": "RESOLVED", "comment": "Problema solucionado"}, format="json")
        assert resp.status_code == status.HTTP_200_OK, f"Error cambiando a RESOLVED: {resp.status_code} - {resp.data}"

        # 4. Probar estado inválido (debe dar 400)
        resp = client.post(f"/api/v1/paquete3/incidents/{code}/change-status/", {"status": "INVALID_STATE"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, "Debería retornar 400 para estado inválido"

    test_case("T034: Cambio de Estado e Historial", test_t034_status_and_history)

    # -------------------------------------------------------------------------
    # T037: Comentarios públicos e internos con control de acceso
    # -------------------------------------------------------------------------
    def test_t037_comments_permissions():
        # 1. Admin crea comentario interno
        client.force_authenticate(user=admin_user)
        resp = client.post(f"/api/v1/paquete3/incidents/{code}/comments/", {"body": "Nota interna de admin", "visibility": "INTERNAL"}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, f"Admin no pudo crear comentario interno: {resp.status_code} - {resp.data}"

        # 2. Residente intenta crear comentario interno (debe fallar con 403)
        client.force_authenticate(user=resident_user)
        resp = client.post(f"/api/v1/paquete3/incidents/{code}/comments/", {"body": "Intento malicioso interno", "visibility": "INTERNAL"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN, f"Residente no debería poder crear comentario interno: {resp.status_code}"

        # 3. Residente crea comentario público exitosamente
        resp = client.post(f"/api/v1/paquete3/incidents/{code}/comments/", {"body": "Comentario público de residente", "visibility": "PUBLIC"}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, f"Residente no pudo crear comentario público: {resp.status_code} - {resp.data}"

    test_case("T037: Comentarios Públicos/Internos y Permisos", test_t037_comments_permissions)

    print("\n============================================================")
    print(f" RESUMEN DE PRUEBAS CU19:")
    print(f" - Exitosas: {passed}")
    print(f" - Fallidas: {failed}")
    print("============================================================")

if __name__ == "__main__":
    run_tests()
