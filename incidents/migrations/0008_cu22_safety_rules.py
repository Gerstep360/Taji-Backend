from django.db import migrations

RULES = [
    ('CU22_FIRE', 'Fuego o humo presente', 'FIRE', [r'\bincendio\b', r'\bfuego\b', r'\bllamas\b', r'\bhumo\b'], 3, 70),
    ('CU22_GAS', 'Posible escape de gas', 'GAS', [r'\bfuga de gas\b', r'\bolor a gas\b'], 3, 74),
    ('CU22_ELECTRICAL', 'Riesgo eléctrico activo', 'ELECTRICITY', [r'\bchispas\b', r'\bcables? (pelados?|expuestos?)\b', r'\bagua.{0,40}tablero electrico\b'], 3, 70),
    ('CU22_PERSON', 'Persona en peligro inmediato', 'PERSON', [r'\b(persona|nino|nina|ninos|ninas|vecino).{0,25}(atrapad|inconsciente|electrocutad)', r'\bintento de suicidio\b', r'\bsecuestro\b'], 4, 95),
]


def seed(apps, schema_editor):
    Category = apps.get_model('incidents', 'IncidentCategory')
    for code, name, description, team in [
        ('FIRE', 'Incendios y humo', 'Incendio, fuego, llamas o humo, sin asumir su causa.', 'SECURITY'),
        ('PERSON_SAFETY', 'Personas en peligro', 'Personas atrapadas, inconscientes o amenazas inmediatas a su integridad.', 'SECURITY'),
    ]:
        Category.objects.get_or_create(code=code, defaults={'name':name, 'description':description, 'default_staff_type':team})
    Rule = apps.get_model('incidents', 'RiskRule')
    for code, name, entity, patterns, rank, weight in RULES:
        Rule.objects.get_or_create(code=code, defaults={
            'name': name, 'entity_type': entity, 'weight': weight,
            'conditions': {'patterns': patterns, 'min_rank': rank, 'safe_actions': [
                'Mantén distancia del peligro y avisa al equipo responsable.',
                'Si hay peligro inmediato para personas, contacta a los servicios de emergencia de tu localidad.',
            ]},
            'description': 'Señal contextual verificable; la prioridad final requiere revisión autorizada.',
        })
    Permission = apps.get_model('accounts', 'SystemPermission')
    Rule.objects.get_or_create(code='CU22_SAFE_ACTIONS', defaults={
        'name': 'No recomendar manipulaciones peligrosas', 'entity_type': 'ACTION', 'weight': 0,
        'conditions': {'forbidden_action_patterns': [
            r'\b(toca|manipula|puentea|repara|corta|cortar|tocar|manipular)\b.{0,60}\b(cables?|tablero|gas|corriente|electricidad)\b',
        ]},
    })
    for code, name in [('analyze_incidents', 'Solicitar análisis IA'), ('review_incident_ai', 'Revisar análisis IA')]:
        Permission.objects.get_or_create(code=code, defaults={'name': name, 'module': 'incidents'})


class Migration(migrations.Migration):
    dependencies = [('incidents', '0007_incident_ai_execution_review')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
