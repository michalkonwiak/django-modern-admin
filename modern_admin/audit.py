from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.http import HttpRequest

from modern_admin.models import AuditEvent


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
        object_label=str(obj),
        metadata=dict(metadata or {}),
    )


def events_for(obj: models.Model) -> models.QuerySet[AuditEvent]:
    return AuditEvent.objects.filter(
        resource_type=obj._meta.label_lower,
        resource_id=str(obj.pk),
    ).select_related("actor")
