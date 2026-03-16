from django.db import models

# Create your models here.
import uuid
from django.db import models


class CommissionAllocation(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    invoice_no = models.CharField(max_length=100)
    receipt_no = models.CharField(max_length=100)
    class_name = models.CharField(max_length=100)

    allocated_amt = models.DecimalField(max_digits=12, decimal_places=2)
    levied = models.DecimalField(max_digits=12, decimal_places=2)

    allocation_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.invoice_no} - {self.receipt_no}"