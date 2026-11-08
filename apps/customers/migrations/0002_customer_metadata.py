from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customers", "0001_initial")]

    operations = [
        migrations.RemoveConstraint(model_name="customer", name="customer_name_not_empty"),
        migrations.AlterField(model_name="customer", name="customer_name", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="customer", name="residence", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddField(model_name="customer", name="route", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddField(model_name="customer", name="memo", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="customer", name="admin_notes", field=models.TextField(blank=True, default="")),
        migrations.AddConstraint(model_name="customer", constraint=models.CheckConstraint(condition=models.Q(customer_name="") | models.Q(customer_name__regex=r"\S"), name="customer_name_valid")),
    ]
