from django.db import migrations


CREATE_EXCLUSION = """
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE reservation
ADD CONSTRAINT ex_reservation_no_overlap
EXCLUDE USING gist (
    common_area_id WITH =,
    tstzrange(start_at, end_at, '[)') WITH &&
)
WHERE (status IN ('PENDING', 'APPROVED'));
"""

DROP_EXCLUSION = """
ALTER TABLE reservation
DROP CONSTRAINT IF EXISTS ex_reservation_no_overlap;
"""


def create_postgres_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_EXCLUSION)


def drop_postgres_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_EXCLUSION)


class Migration(migrations.Migration):
    dependencies = [("community", "0002_initial")]

    operations = [
        migrations.RunPython(create_postgres_exclusion, drop_postgres_exclusion),
    ]