from django.db import migrations


def seed(apps, schema_editor):
    Rule = apps.get_model('incidents', 'RiskRule')
    rows = [
        ('CU22_FIREARM_HARM', 'Disparo, lesión por arma o amenaza grave', 'VIOLENCE', [
            r'\b(?:disparad[oa]s?|disparan|dispara|disparo|disparando)\b.{0,55}\b(?:piernas?|cabeza|pecho|personas?|chic[oa]s?|ninos?|ninas?|alguien|vecin[oa]s?)\b',
            r'\b(?:balazos?|balead[oa]s?|tiroteo|balacera|apunalad[oa]s?|acuchillad[oa]s?)\b',
            r'\b(?:disparos|detonaciones de arma|herid[oa]s? de bala)\b',
            r'\b(?:amenaza|amenazan|amenazando)\b.{0,55}\b(?:matar|disparar)\w*',
        ]),
        ('CU22_SEVERE_BLEEDING', 'Sangrado grave comunicado', 'MEDICAL', [
            r'\b(?:hemorragia|sangrado abundante|sangrando mucho|no deja de sangrar)\b',
        ]),
    ]
    for code, name, entity, patterns in rows:
        Rule.objects.get_or_create(code=code, defaults={'name':name,'entity_type':entity,'weight':100,
            'conditions':{'patterns':patterns,'min_rank':4,'active_contexts':['present','past'],'safe_actions':[
                'Mantén distancia del peligro, no confrontes a las personas involucradas y contacta a seguridad.',
                'Si hay lesiones o una amenaza inmediata, contacta a los servicios de emergencia de tu localidad.',
            ]}, 'description':'No se minimiza una amenaza explícita por describirse como juego, desafío o meme; requiere revisión autorizada.'})


class Migration(migrations.Migration):
    dependencies = [('incidents','0010_ai_worker_heartbeat')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
