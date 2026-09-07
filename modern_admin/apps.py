from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ModernAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modern_admin"
    verbose_name = _("Modern Admin")

    def ready(self) -> None:
        from modern_admin import checks  # noqa: F401
