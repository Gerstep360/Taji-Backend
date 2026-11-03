"""Regression checks for the integrated CU routes and database bootstrap."""
from unittest import skipUnless

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import resolve


class PackageRouteTests(SimpleTestCase):
    def test_legacy_and_package_routes_use_the_same_implementations(self):
        for suffix in (
            "auth/login/", "roles/", "condominiums/current/", "sectors/",
            "units/", "residents/", "resident-units/", "resident-directory/", "staff/",
        ):
            with self.subTest(route=suffix):
                legacy = resolve(f"/api/v1/{suffix}")
                packaged = resolve(f"/api/v1/paquete1/{suffix}")
                self.assertIs(legacy.func.cls, packaged.func.cls)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL sequences only")
class CondominiumSequenceMigrationTests(TransactionTestCase):
    def test_seeded_condominium_does_not_collide_with_next_automatic_id(self):
        before = [("condominiums", "0004_sync_approved_residents")]
        after = [("condominiums", "0005_sync_condominium_sequence")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            # El modelo actual incluye campos SaaS que aún no existían en 0004.
            Condominium = executor.loader.project_state(before).apps.get_model("condominiums", "Condominium")
            seed, _ = Condominium.objects.get_or_create(pk=1, defaults={"name": "Taji"})
            with connection.cursor() as cursor:
                cursor.execute("SELECT setval(pg_get_serial_sequence('condominium', 'id'), 1, false)")
            migrated = MigrationExecutor(connection)
            migrated.migrate(after)
            Condominium = migrated.loader.project_state(after).apps.get_model("condominiums", "Condominium")
            created = Condominium.objects.create(name="Secuencia verificada")
            self.assertGreater(created.pk, seed.pk)
            self.assertTrue(Condominium.objects.filter(pk=seed.pk).exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
