import re
import uuid
from pathlib import PurePosixPath

from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from auditlog.services import record_audit_event
from community.models import Agreement

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_AGREEMENT = 10
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "doc", "docx", "xls", "xlsx"}


def storage_prefix(condominium_id, agreement_id):
    return f"agreements/{condominium_id}/{agreement_id}/"


def safe_file_name(raw_name):
    name = PurePosixPath(str(raw_name).replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or "archivo")[:120]


def validate_upload(upload):
    name = safe_file_name(upload.name)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError({"file": "Formato no permitido. Usa PDF, imágenes, Word o Excel."})
    if upload.size > MAX_ATTACHMENT_BYTES:
        raise ValidationError({"file": "El archivo supera el máximo de 10 MB."})
    return name


def store_attachment(agreement, condominium_id, upload, name):
    target = f"{storage_prefix(condominium_id, agreement.pk)}{uuid.uuid4().hex[:12]}-{name}"
    upload.seek(0)
    return default_storage.save(target, upload)


def delete_stored_file(path):
    try:
        if path and default_storage.exists(path):
            default_storage.delete(path)
    except Exception:  # noqa: BLE001 - un archivo huérfano no debe romper la operación
        pass


def audit(request, obj, action, *, before=None, after=None, description=""):
    record_audit_event(
        action_code=f"CU29_{action}",
        resource_type=obj.__class__.__name__,
        resource_id=obj.pk,
        description=description[:240],
        actor_user=request.user,
        before_data=before,
        after_data=after,
        request=request,
    )


def mark_overdue_agreements(condominium_id):
    """Pasa a Vencido los acuerdos abiertos cuyo plazo ya expiró (transición del sistema)."""
    return Agreement.objects.filter(
        assembly__condominium_id=condominium_id,
        status__in=(Agreement.Status.PENDING, Agreement.Status.IN_PROGRESS),
        due_at__isnull=False,
        due_at__lt=timezone.now(),
    ).update(status=Agreement.Status.OVERDUE)
