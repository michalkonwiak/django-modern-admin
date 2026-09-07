from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.http import HttpRequest

if TYPE_CHECKING:
    from django.db import models


@dataclass(frozen=True, slots=True)
class DetailSection:
    title: str
    fields: tuple[str, ...] | list[str]
    description: str = ""
    columns: int = 2
    template_name: str = "modern_admin/components/detail_section.html"


@dataclass(frozen=True, slots=True)
class DetailTab:
    key: str
    label: str
    template_name: str
    icon: str = ""
    lazy: bool = True
    context: Callable[[HttpRequest, models.Model], Mapping[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class RelatedObjectList:
    """A paginated detail tab using a registered child resource's UI and permissions.

    relation_field is the child's ForeignKey (or M2M field) pointing to the parent.
    Editing and actions use the child resource's existing guarded endpoints.
    """

    key: str
    label: str
    resource_key: str
    relation_field: str
    page_size: int = 25
    icon: str = "list"
    template_name: str = "modern_admin/partials/related_object_list.html"
    context: None = None
    lazy: bool = True
