from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("etims", "0003_etimstransactionlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="debitcredit",
            name="original_reference",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=100,
                null=True,
            ),
        ),
    ]
