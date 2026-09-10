"""Inspect Django's deletion graph before offering or executing a deletion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.deletion import Collector, ProtectedError, RestrictedError
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from modern_admin.exceptions import NotRegistered
from modern_admin.permissions import PermissionPolicy

if TYPE_CHECKING:
    from modern_admin.resources import ModelResource

PROTECTED_MESSAGE = _(
    "This record cannot be deleted because other records depend on it. "
    "Remove or reassign those relationships first."
)


class DeletionCollector(Collector):
    def can_fast_delete(self, *args, **kwargs):
        # Every cascade must be inspected, including models without delete signals.
        return False


@dataclass(frozen=True)
class DeletionPreview:
    summary: tuple[tuple[str, int], ...]
    fingerprint: str


def deletion_preview(
    request: HttpRequest, resource: ModelResource, obj: models.Model, *, using: str
) -> DeletionPreview:
    collector = DeletionCollector(using=using, origin=obj)
    try:
        collector.collect([obj])
    except (ProtectedError, RestrictedError) as exc:
        # Never expose labels of objects the operator may not be able to view.
        raise ValidationError(PROTECTED_MESSAGE) from exc

    summary = []
    identities = []
    for model, objects in collector.data.items():
        identities.extend((model._meta.label_lower, str(item.pk)) for item in objects)
        if model._meta.auto_created:
            continue  # Implicit many-to-many links have no model permissions.
        try:
            related = resource.site.registry.get_for_model(model)
        except NotRegistered:
            policy = PermissionPolicy(model)
            permitted = all(policy.can_delete(request.user, item) for item in objects)
        else:
            ids = {item.pk for item in objects}
            scoped_ids = set(
                related.get_queryset(request)
                .using(using)
                .filter(pk__in=ids)
                .values_list("pk", flat=True)
            )
            permitted = ids <= scoped_ids and all(
                related.can_delete(request, item) for item in objects
            )
        if not permitted:
            raise ValidationError(_("You do not have permission to delete all related records."))
        summary.append((str(model._meta.verbose_name_plural), len(objects)))

    payload = [resource.site.name, resource.key, using, str(request.user.pk), sorted(identities)]
    fingerprint = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    return DeletionPreview(tuple(sorted(summary)), fingerprint)
