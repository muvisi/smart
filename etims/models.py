import uuid
from django.db import models


class DebitCredit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    debit_credit_reference = models.CharField(max_length=100, unique=True, db_index=True)
    source_pushnote_code = models.BigIntegerField(db_index=True)
    transaction_code = models.BigIntegerField(null=True, blank=True, db_index=True)
    client_pin = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=255)
    transaction_total_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    sync_status = models.CharField(max_length=20, default="PENDING", db_index=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
    etims_status = models.CharField(max_length=20, default="PENDING", db_index=True)
    kra_ref = models.TextField(null=True, blank=True)
    kra_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "debit_credit_notes"
        ordering = ["-created_at"]

    def __str__(self):
        return self.debit_credit_reference