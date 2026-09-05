from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest

ModelT = TypeVar("ModelT", bound=models.Model)
ActionPlacement = Literal["row", "detail", "bulk", "resource"]
ActionVariant = Literal["primary", "secondary", "danger"]


@dataclass(frozen=True, slots=True)
class ActionResult:
    message: str
    level: Literal["success", "info", "warning", "error"] = "success"
    refresh: tuple[str, ...] = ()
    redirect_url: str | None = None

    @classmethod
    def success(
        cls,
        message: str,
        *,
        refresh: tuple[str, ...] = (),
        redirect_url: str | None = None,
    ) -> ActionResult:
        return cls(message=message, refresh=refresh, redirect_url=redirect_url)


class ConfirmationForm(forms.Form):
    confirmed = forms.BooleanField(initial=True, widget=forms.HiddenInput)


class ResourceAction(Generic[ModelT]):
    key = ""
    label = "Action"
    description = ""
    icon = "zap"
    variant: ActionVariant = "secondary"
    placements: tuple[ActionPlacement, ...] = ("detail", "row")
    form_class: type[forms.Form] | None = None
    atomic = True

    def __init__(self) -> None:
        if not self.key:
            self.key = self.__class__.__name__.removesuffix("Action").lower()

    def has_permission(self, request: HttpRequest, obj: ModelT | None = None) -> bool:
        resource = getattr(self, "resource", None)
        return bool(resource and resource.permission_policy.can_execute(request, self.key, obj))

    def get_form_class(self) -> type[forms.Form]:
        return self.form_class or ConfirmationForm

    def get_unavailable_reason(self, request: HttpRequest, obj: ModelT | None) -> str:
        """State/business preconditions, separate from authorization."""
        return ""

    def validate_execution(self, request: HttpRequest, obj: ModelT | None) -> None:
        if reason := self.get_unavailable_reason(request, obj):
            raise ValidationError(reason)

    def get_form_kwargs(
        self,
        *,
        request: HttpRequest,
        obj: ModelT | None,
    ) -> dict[str, Any]:
        return {
            "data": request.POST if request.method == "POST" else None,
            "files": request.FILES if request.method == "POST" else None,
        }

    def execute(
        self,
        *,
        request: HttpRequest,
        obj: ModelT,
        cleaned_data: Mapping[str, Any],
    ) -> ActionResult:
        raise NotImplementedError(f"{self.__class__.__name__}.execute() must be implemented")

    def execute_bulk(
        self,
        *,
        request: HttpRequest,
        queryset: models.QuerySet[ModelT],
        cleaned_data: Mapping[str, Any],
    ) -> ActionResult:
        raise NotImplementedError(f"{self.__class__.__name__}.execute_bulk() must be implemented")
