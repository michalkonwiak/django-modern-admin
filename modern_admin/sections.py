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
