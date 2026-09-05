from django.apps import AppConfig


class ModernAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modern_admin"
    verbose_name = "Modern Admin"

    def ready(self) -> None:
        from modern_admin import checks  # noqa: F401
