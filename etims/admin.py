
# Register your models here.
from django.contrib import admin
from .models import DebitCredit


@admin.register(DebitCredit)
class DebitCreditAdmin(admin.ModelAdmin):
    list_display = (
        "debit_credit_reference",
        "source_pushnote_code",
        "transaction_code",
        "client_name",
        "transaction_total_amount",
        "sync_status",
        "etims_status",
        "created_at",
    )

    list_filter = (
        "sync_status",
        "etims_status",
        "created_at",
    )

    search_fields = (
        "debit_credit_reference",
        "client_name",
        "client_pin",
        "kra_ref",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "last_synced_at",
    )

    ordering = ("-created_at",)