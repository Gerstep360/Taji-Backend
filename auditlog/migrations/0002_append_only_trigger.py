from django.db import migrations


CREATE_APPEND_ONLY = """
CREATE OR REPLACE FUNCTION prevent_audit_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event es append-only: no se permite UPDATE ni DELETE';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_no_update
BEFORE UPDATE ON audit_event
FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

CREATE TRIGGER trg_audit_no_delete
BEFORE DELETE ON audit_event
FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
"""

DROP_APPEND_ONLY = """
DROP TRIGGER IF EXISTS trg_audit_no_update ON audit_event;
DROP TRIGGER IF EXISTS trg_audit_no_delete ON audit_event;
DROP FUNCTION IF EXISTS prevent_audit_mutation();
"""


def create_postgres_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_APPEND_ONLY)


def drop_postgres_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_APPEND_ONLY)


class Migration(migrations.Migration):
    dependencies = [("auditlog", "0001_initial")]

    operations = [
        migrations.RunPython(create_postgres_triggers, drop_postgres_triggers),
    ]