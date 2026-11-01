"""Comprobación real T129/T133. Usa exclusivamente reportes sintéticos."""
import json
import math
import os
from time import monotonic
from statistics import median
from django.conf import settings
from django.core.management.base import BaseCommand
from incidents.models import IncidentCategory, PriorityLevel
from paquetes.paquete3_incidencias_ia.cu22_analisis_ia.provider import analyze, ProviderFailure
from paquetes.paquete3_incidencias_ia.cu22_analisis_ia.serializers import PredictionSerializer

CASES = ['Hay incendio y los niños están lejos.', 'No hay incendio. Solo necesito limpiar el pasillo.',
         'Hay agua entrando al tablero eléctrico.']


class Command(BaseCommand):
    help = 'Mide NVIDIA con 1–5 solicitudes sintéticas; no crea incidencias ni modifica datos.'

    def add_arguments(self, parser):
        parser.add_argument('--samples', type=int, default=3)
        parser.add_argument('--output')

    def handle(self, *args, **options):
        categories = list(IncidentCategory.objects.filter(is_active=True).values('code','name','description'))
        priorities = list(PriorityLevel.objects.filter(is_active=True).values('code','name','rank'))
        durations, results = [], []
        for i in range(max(1,min(5,options['samples']))):
            start = monotonic()
            try:
                prediction, _ = analyze({'title':'Prueba sintética CU22','description':CASES[i%len(CASES)],'location':'Pasillo de prueba'},categories,priorities)
                validator = PredictionSerializer(data=prediction)
                valid = validator.is_valid()
                results.append({'sample':i+1,'success':valid,'category':prediction.get('category_code'),
                                'priority':prediction.get('priority_code'),'error':None if valid else 'invalid_response'})
            except ProviderFailure as error:
                results.append({'sample':i+1,'success':False,'error':error.code})
            durations.append(round((monotonic()-start)*1000))
        ordered = sorted(durations)
        try:
            import resource
            rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except ImportError:
            rss_kb = None
        report = {'model':settings.NVIDIA['MODEL'],'samples':len(results),
                  'scope':'provider_connectivity_and_schema_only', 'semantic_quality_evaluated':False,
                  'successful':sum(r['success'] for r in results),'duration_ms':durations,
                  'p50_ms':median(durations),'p95_ms':ordered[math.ceil(.95*len(ordered))-1],
                  'process_max_rss_kb':rss_kb,'cpu_count':os.cpu_count(),'results':results}
        rendered = json.dumps(report,ensure_ascii=False,indent=2)
        if options['output']:
            from pathlib import Path
            Path(options['output']).write_text(rendered,encoding='utf-8')
        self.stdout.write(rendered)
