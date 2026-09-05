from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from django.db import models
from django.db.models import Q, QuerySet
from django.http import HttpRequest

from modern_admin.exceptions import InvalidResourceConfiguration

ModelT = TypeVar("ModelT", bound=models.Model)


@dataclass(frozen=True, slots=True)
class WorkQueue(Generic[ModelT]):
    """A curated work list; conditions always narrow the resource's scoped queryset."""

    key: str
    label: str
    condition: Q | Callable[[HttpRequest], Q]
    description: str = ""
    permission: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", self.key) or self.key == "all":
            raise InvalidResourceConfiguration(
                f"WorkQueue key '{self.key}' must be a lowercase slug other than 'all'."
            )
        if not self.label.strip():
            raise InvalidResourceConfiguration(f"WorkQueue '{self.key}' needs a label.")

    def has_permission(self, request: HttpRequest) -> bool:
        return bool(
            request.user.is_authenticated
            and (not self.permission or request.user.has_perm(self.permission))
        )

    def get_condition(self, request: HttpRequest) -> Q:
        condition = self.condition(request) if callable(self.condition) else self.condition
        if not isinstance(condition, Q):
            raise InvalidResourceConfiguration(
                f"WorkQueue '{self.key}'.condition must return a Django Q object."
            )
        return condition

    def apply(self, request: HttpRequest, queryset: QuerySet[ModelT]) -> QuerySet[ModelT]:
        return queryset.filter(self.get_condition(request)).distinct()
