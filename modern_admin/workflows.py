from __future__ import annotations

from typing import TypeVar

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.http import HttpRequest

from modern_admin.actions import ResourceAction
from modern_admin.exceptions import InvalidResourceConfiguration

ModelT = TypeVar("ModelT", bound=models.Model)


class TransitionAction(ResourceAction[ModelT]):
    """A guarded action, not an ORM state setter. execute() calls your domain service."""

    state_field: str = "status"
    from_states: tuple[str, ...] = ()
    unavailable_message: str = "The record's state has changed. This action is no longer available."

    def validate_configuration(self, model: type[ModelT]) -> None:
        try:
            field = model._meta.get_field(self.state_field)
        except FieldDoesNotExist as exc:
            raise InvalidResourceConfiguration(
                f"{type(self).__name__}.state_field '{self.state_field}' "
                f"is not a {model.__name__} field."
            ) from exc
        if not self.atomic or not self.from_states or field.is_relation:
            raise InvalidResourceConfiguration(
                f"{type(self).__name__} requires atomic=True, from_states and a scalar state_field."
            )
        choices = {value for value, _ in field.flatchoices}
        if choices and not set(self.from_states) <= choices:
            raise InvalidResourceConfiguration(
                f"{type(self).__name__}.from_states includes values "
                f"outside {self.state_field} choices."
            )
        if set(self.placements) - {"row", "detail"}:
            raise InvalidResourceConfiguration(
                f"{type(self).__name__} supports row/detail placement; "
                "use a service for bulk transitions."
            )

    def get_unavailable_reason(self, request: HttpRequest, obj: ModelT | None) -> str:
        if obj is None or getattr(obj, self.state_field) not in self.from_states:
            return self.unavailable_message
        return super().get_unavailable_reason(request, obj)
