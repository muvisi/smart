import uuid

from django.db import models


class GxSmartMemberSyncLog(models.Model):
    STATUS_CHOICES = (
        (1, "Success"),
        (2, "Failure"),
        (3, "Skipped"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family_code = models.CharField(max_length=100, blank=True, null=True)
    membership_number = models.CharField(max_length=100, blank=True, null=True)
    old_membership_number = models.CharField(max_length=100, blank=True, null=True)
    request_object = models.JSONField(null=True, blank=True)
    response_object = models.JSONField(null=True, blank=True)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES)
    sent_to_smart = models.BooleanField(default=False)
    http_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gxsmart_member_sync_logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.membership_number} - {self.get_status_display()}"
