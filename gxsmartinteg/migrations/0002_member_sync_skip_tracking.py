from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gxsmartinteg", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gxsmartmembersynclog",
            name="status",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "Success"), (2, "Failure"), (3, "Skipped")]
            ),
        ),
        migrations.AddField(
            model_name="gxsmartmembersynclog",
            name="sent_to_smart",
            field=models.BooleanField(default=False),
        ),
    ]
