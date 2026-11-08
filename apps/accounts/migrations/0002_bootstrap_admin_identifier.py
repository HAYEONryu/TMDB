from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.RemoveConstraint(model_name="user", name="user_phone_format"),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(phone_normalized__regex=r"^010[0-9]{8}$")
                | models.Q(phone_normalized="admin", role="ADMIN"),
                name="user_login_identifier_format",
            ),
        ),
    ]
