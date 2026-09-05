from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.compatibility)
def modern_admin_configuration_checks(app_configs: Any, **kwargs: Any) -> list[Error]:
    errors = []
    for middleware in (
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ):
        if middleware not in settings.MIDDLEWARE:
            errors.append(Error(f"Modern Admin requires {middleware}.", id="modern_admin.E001"))
    return errors
