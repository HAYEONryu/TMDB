from django.db import migrations


def create_settings(apps, schema_editor):
    apps.get_model("sites", "GlobalSettings").objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("sites", "0001_initial")]
    operations = [migrations.RunPython(create_settings, migrations.RunPython.noop)]
