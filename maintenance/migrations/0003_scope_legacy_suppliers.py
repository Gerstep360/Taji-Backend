"""Atribuye proveedores antiguos solo cuando el condominio es inequívoco."""
from django.db import migrations


def scope_suppliers(apps, schema_editor):
    Supplier = apps.get_model("maintenance", "Supplier")
    WorkOrder = apps.get_model("maintenance", "WorkOrder")
    alias = schema_editor.connection.alias
    for supplier in Supplier.objects.using(alias).filter(condominium__isnull=True).iterator():
        orders = WorkOrder.objects.using(alias).filter(supplier_id=supplier.pk)
        if orders.filter(condominium__isnull=True).exists():
            continue
        tenant_ids = list(orders.values_list("condominium_id", flat=True).distinct()[:2])
        if len(tenant_ids) == 1:
            Supplier.objects.using(alias).filter(pk=supplier.pk).update(condominium_id=tenant_ids[0])


class Migration(migrations.Migration):
    dependencies = [("maintenance", "0002_workorderstatushistory_supplier_condominium_and_more")]
    operations = [migrations.RunPython(scope_suppliers, migrations.RunPython.noop)]
