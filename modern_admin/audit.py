from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from modern_admin.models import AuditEvent

# The timeline stores machine keys so history survives renames; only the two
# verbs the framework writes itself have a translation of their own. Keys that
# come from a resource action are labelled from that action instead.
BUILTIN_ACTION_LABELS = {"created": _("created"), "updated": _("updated")}


def action_label(action: str) -> str:
    """Human-readable verb for a recorded audit action."""
    return str(BUILTIN_ACTION_LABELS.get(action, action.replace("_", " ")))


def record_event(
    *,
    request: HttpRequest,
    action: str,
    obj: models.Model,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    actor = request.user if not isinstance(request.user, AnonymousUser) else None
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        resource_type=obj._meta.label_lower,
        resource_id=str(obj.pk),
        object_label=str(obj)[:255],
        metadata=dict(metadata or {}),
    )


def events_for(obj: models.Model) -> models.QuerySet[AuditEvent]:
    return AuditEvent.objects.filter(
        resource_type=obj._meta.label_lower,
        resource_id=str(obj.pk),
    ).select_related("actor")
