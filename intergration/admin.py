# engine/admin.py
from django.contrib import admin
from .models import MemberSyncResetLog

@admin.register(MemberSyncResetLog)
class MemberSyncResetLogAdmin(admin.ModelAdmin):
    list_display = ("id", "family_no", "anniv", "processed", "errors", "created_at")
    list_filter = ("processed", "created_at")
    search_fields = ("family_no",)
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)