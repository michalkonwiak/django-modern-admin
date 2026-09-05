import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("modern_admin", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SavedView",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("site_name", models.CharField(max_length=100)),
                ("resource_key", models.CharField(max_length=100)),
                ("name", models.CharField(max_length=100)),
                ("query_string", models.CharField(max_length=2000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="modern_admin_saved_views",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.AddConstraint(
            model_name="savedview",
            constraint=models.UniqueConstraint(
                fields=("user", "site_name", "resource_key", "name"),
                name="modern_admin_unique_saved_view",
            ),
        ),
    ]
