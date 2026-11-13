"""Servidor local de integración: base SQLite de pruebas en memoria, nunca PostgreSQL real.

Ejecutar desde Backend con .venv/Scripts/python.exe scripts/serve_cu24_test_api.py.
Detener con Ctrl+C después de e2e/cu24-live.spec.ts. No usar en producción.
"""
import io
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from wsgiref.simple_server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_test'

import django
django.setup()
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.test.utils import setup_databases, teardown_databases
from django.utils import timezone
from accounts.models import Person, Role, User
from condominiums.models import Condominium, Sector, Resident
from incidents.models import Incident, IncidentCategory, PriorityLevel
from maintenance.models import Asset, AssetType, MaintenancePlan, WorkOrder
from tenancy.models import TenantMembership
import segno

settings.ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
settings.CORS_ALLOWED_ORIGINS = ['http://localhost:4201']
settings.CSRF_TRUSTED_ORIGINS = ['http://localhost:4201']
settings.AUTH_COOKIE_SECURE = False
settings.AUTH_COOKIE_DOMAIN = None
settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
database = setup_databases(verbosity=0, interactive=False)
try:
    own = Condominium.objects.create(name='CU24 Prueba local', slug='cu24-live')
    other = Condominium.objects.create(name='CU24 Otro condominio', slug='cu24-other')
    for slug in ['administrador', 'residente']:
        role = Role.objects.get(slug=slug)
        person = Person.objects.create(first_name='CU24', last_name=slug, document_number='LIVE-' + slug)
        user = User.objects.create_user(email=slug + '@cu24.test', password='OnlyLocal-CU24-123!', role=role, person=person)
        TenantMembership.objects.create(user=user, condominium=own, role=role, is_default=True)
        if slug == 'residente':
            Resident.objects.create(person=person, condominium=own)
    kind = AssetType.objects.create(code='CU24-LIVE', name='Bomba de prueba')
    for condo, prefix in [(own, '11111111'), (other, '22222222')]:
        sector = Sector.objects.create(condominium=condo, code='S-' + prefix, name='Sala de bombas')
        asset = Asset.objects.create(asset_type=kind, sector=sector, code='ACT-' + prefix,
            name='Bomba principal ' + prefix, qr_uuid=prefix + '-1111-4111-8111-111111111111')
        if condo == own:
            Incident.objects.create(condominium=own, asset=asset, title='Fuga en la bomba', public_code='INC-CU24-LIVE',
                category=IncidentCategory.objects.first(), priority=PriorityLevel.objects.first())
            WorkOrder.objects.create(asset=asset, public_code='OT-CU24-LIVE', title='Inspección programada', work_type='INSPECTION')
            MaintenancePlan.objects.create(asset=asset, name='Revisión trimestral', frequency_days=90, next_due_at=timezone.now() + timedelta(days=90))
    qr = io.BytesIO()
    segno.make('TAJI-ASSET.11111111111141118111111111111111', micro=False).save(qr, kind='png', scale=8)
    application = get_wsgi_application()
    def fixture_application(environ, start_response):
        if environ['PATH_INFO'] == '/__cu24_fixture.png':
            start_response('200 OK', [('Content-Type', 'image/png')])
            return [qr.getvalue()]
        return application(environ, start_response)
    with make_server('127.0.0.1', 18766, fixture_application) as server:
        print(json.dumps({'ready': True, 'url': 'http://localhost:18766', 'database': 'SQLite test memory only'}), flush=True)
        server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    teardown_databases(database, verbosity=0)
