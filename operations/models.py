from django.conf import settings
from django.db import models


class OperationsRecord(models.Model):
    class Kind(models.TextChoices):
        WARRANTY = "warranties", "Garantías"
        QUOTE = "quotes", "Cotizaciones"
        INSPECTION = "inspections", "Inspecciones"

    condominium = models.ForeignKey("condominiums.Condominium", on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=120)
    date = models.DateField()
    status = models.CharField(max_length=20)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["condominium", "kind", "date", "id"], name="ops_tenant_kind_date_idx")]


class AnalysisAttempt(models.Model):
    condominium = models.ForeignKey("condominiums.Condominium", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
