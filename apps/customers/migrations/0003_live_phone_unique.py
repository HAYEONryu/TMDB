from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customers", "0002_customer_metadata")]

    operations = [
        migrations.RemoveConstraint(model_name="customer", name="customer_site_phone_unique"),
        migrations.AddConstraint(model_name="customer", constraint=models.UniqueConstraint(
            fields=["site", "phone_normalized"], condition=models.Q(deleted_at__isnull=True),
            name="customer_site_live_phone_unique")),
        migrations.AddIndex(model_name="customer", index=models.Index(fields=["phone_normalized"],
            condition=models.Q(deleted_at__isnull=True), name="customer_live_phone_idx")),
    ]
