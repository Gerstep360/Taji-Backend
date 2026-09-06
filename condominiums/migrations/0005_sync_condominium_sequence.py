"""Keep automatic IDs usable after the explicit pk=1 seed in 0003."""
from django.core.management.color import no_style
from django.db import migrations


def sync_condominium_sequence(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    model = apps.get_model("condominiums", "Condominium")
    for statement in schema_editor.connection.ops.sequence_reset_sql(no_style(), [model]):
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [("condominiums", "0004_sync_approved_residents")]
    operations = [
        migrations.RunPython(sync_condominium_sequence, migrations.RunPython.noop),
    ]
