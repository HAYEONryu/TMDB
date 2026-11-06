from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai_assistant", "0004_airesult_ai_guide_version_positive_and_more")]
    operations = [
        migrations.AddField(model_name="airequest", name="reasoning_effort",
                            field=models.CharField(blank=True, default="", max_length=8)),
        migrations.AddField(model_name="aiusageattempt", name="cached_tokens",
                            field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="aiusageattempt", name="cache_write_tokens",
                            field=models.PositiveIntegerField(default=0)),
    ]
