from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceAccess",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
            ],
            options={
                "verbose_name": "workspace access",
                "verbose_name_plural": "workspace access",
                "permissions": (
                    ("view_workspace_dashboard", "Can view the operations overview"),
                    ("view_workspace_settings", "Can view workspace settings"),
                ),
                "managed": False,
                "default_permissions": (),
            },
        ),
    ]
