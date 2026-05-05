from django.contrib import admin
from .models import CommissionAllocation, CommissionRecord


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

    list_filter = (
        "class_name",
        "allocation_date",
    )

    search_fields = (
        "invoice_no",
        "receipt_no",
        "class_name",
    )

    ordering = ("-allocation_date",)

    readonly_fields = ("id", "allocation_date")


@admin.register(CommissionRecord)
class CommissionRecordAdmin(admin.ModelAdmin):
    list_display = (
        "debit_code",
        "customer_name",
        "push_note_code",
        "policy_number",
        "broker_name",
        "receipted_amount",
        "commission_payable",
        "payment_status",
        "is_paid",
        "updated_at",
    )

    list_filter = (
        "payment_status",
        "is_paid",
        "intermediary_name",
    )

    search_fields = (
        "debit_code",
        "policy_number",
        "push_note_code",
        "broker_name",
        "intermediary_name",
    )

    ordering = ("-updated_at",)

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Identifiers", {
            "fields": ("id", "push_note_code", "debit_no", "transaction_number", "policy_number")
        }),
        ("Parties", {
            "fields": ("agent_code", "customer_code", "intermediary_name", "broker_name")
        }),
        ("Financials", {
            "fields": (
                "receipted_amount",
                "levies",
                "available_allocation",
                "broker_commission",
                "withholding_tax",
                "commission_payable",
                "transaction_total_amount",
            )
        }),
        ("Status", {
            "fields": ("payment_status", "is_paid")
        }),
        ("Meta", {
            "fields": ("created_at", "updated_at")
        }),
    )