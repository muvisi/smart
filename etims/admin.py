
# Register your models here.
from django.contrib import admin
from .models import DebitCredit, EtimsTransactionLog


class EtimsTransactionLogInline(admin.TabularInline):
    model = EtimsTransactionLog
    extra = 0
    can_delete = False
    fields = (
        "status",
        "response_status_code",
        "created_at",
        "completed_at",
    )
    readonly_fields = fields
    show_change_link = True


@admin.register(DebitCredit)
class DebitCreditAdmin(admin.ModelAdmin):
    inlines = (EtimsTransactionLogInline,)
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


@admin.register(EtimsTransactionLog)
class EtimsTransactionLogAdmin(admin.ModelAdmin):
    list_display = (
        "debit_credit",
        "status",
        "response_status_code",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "response_status_code", "created_at")
    search_fields = (
        "debit_credit__debit_credit_reference",
        "debit_credit__source_pushnote_code",
        "error_message",
    )
    readonly_fields = (
        "debit_credit",
        "request_url",
        "request_payload",
        "response_payload",
        "response_status_code",
        "status",
        "error_message",
        "created_at",
        "completed_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False
