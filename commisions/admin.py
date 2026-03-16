from django.contrib import admin
from .models import CommissionAllocation


@admin.register(CommissionAllocation)
class CommissionAllocationAdmin(admin.ModelAdmin):

    list_display = (
        "invoice_no",
        "receipt_no",
        "class_name",
        "allocated_amt",
        "levied",
        "allocation_date",
    )

    search_fields = (
        "invoice_no",
        "receipt_no",
        "class_name",
    )

    list_filter = (
        "allocation_date",
        "class_name",
    )

    ordering = ("-allocation_date",)