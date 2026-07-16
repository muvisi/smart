from django.contrib import admin

from .models import GxSmartMemberSyncLog


@admin.register(GxSmartMemberSyncLog)
class GxSmartMemberSyncLogAdmin(admin.ModelAdmin):
    list_display = (
        "membership_number",
        "old_membership_number",
        "family_code",
        "status",
        "sent_to_smart",
        "http_code",
        "created_at",
    )

    list_filter = (
        "status",
        "sent_to_smart",
        "created_at",
    )

    search_fields = (
        "membership_number",
        "old_membership_number",
        "family_code",
        "error_message",
    )

    readonly_fields = (
        "id",
        "request_object",
        "response_object",
        "created_at",
    )

    ordering = ("-created_at",)

    list_per_page = 50

    fieldsets = (
        (
            "Member Information",
            {
                "fields": (
                    "id",
                    "family_code",
                    "membership_number",
                    "old_membership_number",
                )
            },
        ),
        (
            "Sync Status",
            {
                "fields": (
                    "status",
                    "sent_to_smart",
                    "http_code",
                    "error_message",
                )
            },
        ),
        (
            "Request / Response",
            {
                "fields": (
                    "request_object",
                    "response_object",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_at",
                )
            },
        ),
    )