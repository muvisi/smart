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