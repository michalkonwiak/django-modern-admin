from __future__ import annotations

from typing import Any, Generic, TypeVar

from django.db import models
from django.http import HttpRequest

ModelT = TypeVar("ModelT", bound=models.Model)
UserLike = Any


class PermissionPolicy(Generic[ModelT]):
    """Default policy backed by Django's four model permissions."""

    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    def _permission_name(self, action: str) -> str:
        opts = self.model._meta
        return f"{opts.app_label}.{action}_{opts.model_name}"

    def can_view(self, user: UserLike, obj: ModelT | None = None) -> bool:
        permission = self._permission_name("view")
        return bool(
            user.is_authenticated and (user.has_perm(permission, obj) or user.has_perm(permission))
        )

    def can_add(self, user: UserLike) -> bool:
        return bool(user.is_authenticated and user.has_perm(self._permission_name("add")))

    def can_change(self, user: UserLike, obj: ModelT | None = None) -> bool:
        permission = self._permission_name("change")
        return bool(
            user.is_authenticated and (user.has_perm(permission, obj) or user.has_perm(permission))
        )

    def can_delete(self, user: UserLike, obj: ModelT | None = None) -> bool:
        permission = self._permission_name("delete")
        return bool(
            user.is_authenticated and (user.has_perm(permission, obj) or user.has_perm(permission))
        )

    def can_execute(self, request: HttpRequest, action: str, obj: ModelT | None = None) -> bool:
        return self.can_change(request.user, obj)
