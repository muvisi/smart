from django.db import models
import uuid


class CommissionAllocation(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    invoice_no = models.CharField(max_length=50)
    receipt_no = models.CharField(max_length=50)

    class_name = models.CharField(max_length=100)

    allocated_amt = models.DecimalField(max_digits=18, decimal_places=2)
    levied = models.DecimalField(max_digits=18, decimal_places=2)

    allocation_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "commission_allocations"
        ordering = ["-allocation_date"]
        indexes = [
            models.Index(fields=["invoice_no"]),
            models.Index(fields=["receipt_no"]),
            models.Index(fields=["allocation_date"]),
        ]

    def __str__(self):
        return f"{self.invoice_no} - {self.receipt_no} - {self.allocated_amt}"
    
    
import uuid
from django.db import models

class PaymentStatus(models.TextChoices):
    FULLY_PAID = "Fully Paid"
    PARTIALLY_PAID = "Partially Paid"
    UNPAID = "Unpaid"


class CommissionRecord(models.Model):
   
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    push_note_code = models.IntegerField( null=True, blank=True)
    transaction_number = models.IntegerField(null=True, blank=True)
    debit_code = models.CharField(max_length=100, null=True, blank=True)
    policy_number = models.CharField(max_length=100, null=True, blank=True)
    customer_name = models.CharField(max_length=200, null=True, blank=True)

    agent_code = models.IntegerField(null=True, blank=True)
    customer_code = models.IntegerField(null=True, blank=True)
    intermediary_name = models.CharField(max_length=255, null=True, blank=True)
    broker_name = models.CharField(max_length=255, null=True, blank=True)
    push_note_request_date = models.DateTimeField(null=True, blank=True)
    receipted_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    levies = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    available_allocation = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    broker_commission = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    withholding_tax = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    commission_payable = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    transaction_total_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    paid_by = models.CharField(max_length=150, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    primarybenefitname = models.CharField(max_length=255, null=True, blank=True)
    customerspolicycode = models.IntegerField(null=True, blank=True)
    primarybenefitcode = models.IntegerField(null=True, blank=True)
    # Audit (keep strict)
    payment_status = models.CharField(
    max_length=200,
    choices=PaymentStatus.choices,
    null=True,
    blank=True
)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # 🔥 Clean padded strings safely
        if self.intermediary_name:
            self.intermediary_name = self.intermediary_name.strip()
        if self.broker_name:
            self.broker_name = self.broker_name.strip()
        if self.primarybenefitname:
            self.primarybenefitname = self.primarybenefitname.strip()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.debit_code or 'N/A'} - {self.policy_number or 'N/A'}"