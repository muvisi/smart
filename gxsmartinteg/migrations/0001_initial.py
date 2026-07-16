import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="GxSmartMemberSyncLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("family_code", models.CharField(blank=True, max_length=100, null=True)),
                ("membership_number", models.CharField(blank=True, max_length=100, null=True)),
                ("old_membership_number", models.CharField(blank=True, max_length=100, null=True)),
                ("request_object", models.JSONField(blank=True, null=True)),
                ("response_object", models.JSONField(blank=True, null=True)),
                ("status", models.PositiveSmallIntegerField(choices=[(1, "Success"), (2, "Failure")])),
                ("http_code", models.IntegerField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "gxsmart_member_sync_logs",
                "ordering": ["-created_at"],
            },
        ),
    ]
