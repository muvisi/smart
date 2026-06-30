import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("etims", "0002_debitcredit_etims_status_debitcredit_kra_message_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="EtimsTransactionLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_url", models.URLField(max_length=500)),
                ("request_payload", models.JSONField()),
                ("response_payload", models.JSONField(blank=True, null=True)),
                ("response_status_code", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("SUCCESS", "Success"),
                            ("FAILED", "Failed"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "debit_credit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="etims_logs",
                        to="etims.debitcredit",
                    ),
                ),
            ],
            options={
                "db_table": "etims_transaction_logs",
                "ordering": ["-created_at"],
            },
        ),
    ]
