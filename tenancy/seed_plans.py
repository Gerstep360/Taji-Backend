import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from datetime import timedelta
from django.utils import timezone
from tenancy.models import SubscriptionPlan, TenantSubscription
from condominiums.models import Condominium

plans_data = [
    {
        "code": "esencial",
        "name": "Plan Esencial",
        "tagline": "Ideal para condominios pequeños o comunidades residenciales compactas.",
        "description": "Control esencial de accesos y visitantes con tecnología QR rápida.",
        "price_bob": 150.00,
        "price_usd": 22.00,
        "billing_period": "MONTHLY",
        "max_units": 30,
        "max_residents": 100,
        "features": [
            "Hasta 30 departamentos o casas",
            "Pases de visita con Código QR instantáneo",
            "Gestión completa de residentes y unidades",
            "Bitácora digital de accesos en tiempo real",
            "Soporte por correo electrónico 24/7",
        ],
        "is_popular": False,
        "order": 1,
    },
    {
        "code": "profesional",
        "name": "Plan Profesional",
        "tagline": "La opción predilecta para condominios modernos y torres residenciales.",
        "description": "Plataforma completa de seguridad con biometría facial, finanzas y áreas comunes.",
        "price_bob": 350.00,
        "price_usd": 50.00,
        "billing_period": "MONTHLY",
        "max_units": 120,
        "max_residents": 500,
        "features": [
            "Hasta 120 departamentos o casas",
            "Todo lo incluido en el Plan Esencial",
            "Reconocimiento Facial biométrico de alta precisión",
            "Notificaciones push automáticas a residentes",
            "Gestión y reserva de áreas sociales y canchas",
            "Control de expensas y cobros integrados con Stripe",
            "Soporte prioritario y capacitación técnica inicial",
        ],
        "is_popular": True,
        "order": 2,
    },
    {
        "code": "corporativo",
        "name": "Plan Corporativo",
        "tagline": "Para complejos residenciales de gran escala y urbanizaciones privadas.",
        "description": "Potencia empresarial sin límites, con soporte 24/7 y multi-garitas simultáneas.",
        "price_bob": 700.00,
        "price_usd": 100.00,
        "billing_period": "MONTHLY",
        "max_units": 500,
        "max_residents": 2000,
        "features": [
            "Hasta 500 departamentos o casas",
            "Todo lo incluido en el Plan Profesional",
            "Múltiples garitas y accesos simultáneos",
            "Integración con barreras vehiculares y cámaras IP",
            "Auditoría y trazabilidad avanzada de seguridad",
            "Exportación contable y reportes ejecutivos",
            "Gerente de cuenta dedicado y SLA 99.9%",
        ],
        "is_popular": False,
        "order": 3,
    },
]

def run():
    print("Iniciando sembrado de Planes SaaS...")
    for p in plans_data:
        obj, created = SubscriptionPlan.objects.update_or_create(
            code=p["code"],
            defaults=p,
        )
        status_str = "Creado" if created else "Actualizado"
        print(f"Plan {obj.name} -> {status_str}")

    pro_plan = SubscriptionPlan.objects.get(code="profesional")
    now = timezone.now()
    for condo in Condominium.objects.all():
        sub, created = TenantSubscription.objects.get_or_create(
            condominium=condo,
            defaults={
                "plan": pro_plan,
                "status": TenantSubscription.Status.ACTIVE,
                "current_period_start": now,
                "current_period_end": now + timedelta(days=30),
                "trial_ends_at": now + timedelta(days=14),
            },
        )
        print(f"Condominio '{condo.name}' -> Suscripción {sub.plan.name} ({sub.status})")

if __name__ == "__main__":
    run()
