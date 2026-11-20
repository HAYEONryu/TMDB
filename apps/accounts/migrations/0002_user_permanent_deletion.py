from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial')]

    operations = [
        migrations.AddField(model_name='user', name='deleted_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(model_name='user', name='phone_normalized', field=models.CharField(max_length=11, null=True, unique=True)),
        migrations.AddConstraint(model_name='user', constraint=models.CheckConstraint(
            condition=(models.Q(deleted_at__isnull=True, phone_normalized__isnull=False) |
                       models.Q(deleted_at__isnull=False, phone_normalized__isnull=True, is_active=False, password__startswith='!')),
            name='user_deleted_login_disabled',
        )),
    ]
