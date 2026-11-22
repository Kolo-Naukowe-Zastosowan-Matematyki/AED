from django.contrib.postgres.fields import JSONField
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("resources", "0076_wykaz_aed")]
    operations = [
        migrations.CreateModel(
            name="AedPublication",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("csv_sha256", models.CharField(max_length=64)),
                ("total", models.PositiveIntegerField()),
                ("areas", JSONField()),
                ("resource", models.ForeignKey(on_delete=models.CASCADE, to="resources.Resource")),
            ],
        )
    ]
