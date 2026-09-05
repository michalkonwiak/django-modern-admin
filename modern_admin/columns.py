from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.utils.formats import date_format, number_format
from django.utils.text import capfirst

from modern_admin.exceptions import InvalidResourceConfiguration

if TYPE_CHECKING:
    from modern_admin.resources import ModelResource

ModelT = TypeVar("ModelT", bound=models.Model)
CellKind = Literal["text", "badge", "boolean", "money", "number", "date", "avatar", "html"]


def resolve_value(source: Any, path: str) -> Any:
    value = source
    for part in path.split("__"):
        if value is None:
            return None
        value = getattr(value, part)
        if callable(value):
            value = value()
    return value


@dataclass(frozen=True, slots=True)
class Cell:
    display: str
    kind: CellKind = "text"
    secondary: str | None = None
    variant: str = "neutral"
    raw: Any = None
    numeric: bool = False


@dataclass(slots=True)
class Column(Generic[ModelT]):
    accessor: str
    label: str | None = None
    sortable: bool | str = True
    visible: bool = True
    width: str | None = None
    _bound_label: str = field(default="", init=False, repr=False)

    def bind(self, model: type[ModelT], resource: ModelResource[ModelT]) -> Column[ModelT]:
        if self.accessor == "__str__":
            self.sortable = False
            self._bound_label = self.label or capfirst(str(model._meta.verbose_name))
            return self
        root = self.accessor.split("__", 1)[0]
        model_attr = hasattr(model, root)
        resource_attr = hasattr(resource, root)
        try:
            model._meta.get_field(root)
            model_field = True
        except FieldDoesNotExist:
            model_field = False
        if not model_field and not model_attr and not resource_attr:
            raise InvalidResourceConfiguration(
                f"{resource.__class__.__name__}.list_display references '{self.accessor}', "
                f"but {model.__name__} contains no field, property, or resource method "
                f"named '{root}'."
            )
        if not model_field and self.sortable is True:
            self.sortable = False
        if self.label:
            self._bound_label = self.label
        elif model_field:
            self._bound_label = capfirst(str(model._meta.get_field(root).verbose_name))
        else:
            self._bound_label = capfirst(root.replace("_", " "))
        return self

    @property
    def heading(self) -> str:
        return self._bound_label or self.label or capfirst(self.accessor.replace("_", " "))

    @property
    def ordering_key(self) -> str | None:
        if self.sortable is False:
            return None
        return self.sortable if isinstance(self.sortable, str) else self.accessor

    def get_value(self, obj: ModelT, resource: ModelResource[ModelT]) -> Any:
        if self.accessor == "__str__":
            return str(obj)
        root = self.accessor.split("__", 1)[0]
        if hasattr(resource, root) and callable(getattr(resource, root)):
            return getattr(resource, root)(obj)
        return resolve_value(obj, self.accessor)

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        value = self.get_value(obj, resource)
        return Cell(display=resource.format_value(value), raw=value)


@dataclass(slots=True)
class TextColumn(Column[ModelT]):
    secondary: str | Callable[[ModelT], Any] | None = None

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        value = self.get_value(obj, resource)
        secondary_value = None
        if callable(self.secondary):
            secondary_value = self.secondary(obj)
        elif self.secondary:
            secondary_value = resolve_value(obj, self.secondary)
        return Cell(
            display=resource.format_value(value),
            secondary=resource.format_value(secondary_value)
            if secondary_value is not None
            else None,
            raw=value,
        )


@dataclass(slots=True)
class RelationColumn(TextColumn[ModelT]):
    pass


@dataclass(slots=True)
class BadgeColumn(Column[ModelT]):
    variants: Mapping[Any, str] = field(default_factory=dict)
    labels: Mapping[Any, str] = field(default_factory=dict)

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        value = self.get_value(obj, resource)
        display_method = getattr(obj, f"get_{self.accessor}_display", None)
        display = (
            display_method()
            if display_method
            else self.labels.get(value, resource.format_value(value))
        )
        return Cell(
            display=str(display),
            kind="badge",
            variant=self.variants.get(value, "neutral"),
            raw=value,
        )


@dataclass(slots=True)
class MoneyColumn(Column[ModelT]):
    currency: str = "USD"

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        value = self.get_value(obj, resource)
        if value is None:
            return Cell(display="—", kind="money", numeric=True)
        amount = Decimal(value)
        symbols = {"USD": "$", "EUR": "€", "GBP": "£", "PLN": "zł "}
        prefix = symbols.get(self.currency, f"{self.currency} ")
        formatted = number_format(amount, decimal_pos=2, use_l10n=True, force_grouping=True)
        return Cell(
            display=f"{prefix}{formatted}",
            kind="money",
            raw=value,
            numeric=True,
        )


@dataclass(slots=True)
class NumberColumn(Column[ModelT]):
    decimal_places: int | None = None

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        value = self.get_value(obj, resource)
        display = (
            "—"
            if value is None
            else number_format(
                value, decimal_pos=self.decimal_places, use_l10n=True, force_grouping=True
            )
        )
        return Cell(display=str(display), kind="number", raw=value, numeric=True)


@dataclass(slots=True)
class BooleanColumn(Column[ModelT]):
    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        value = bool(self.get_value(obj, resource))
        return Cell(
            display="Yes" if value else "No",
            kind="boolean",
            variant="success" if value else "neutral",
            raw=value,
        )


@dataclass(slots=True)
class DateColumn(Column[ModelT]):
    format: str = "M j, Y"

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        value = self.get_value(obj, resource)
        display = date_format(value, self.format) if isinstance(value, (date, datetime)) else "—"
        return Cell(display=display, kind="date", raw=value)


@dataclass(slots=True)
class DateTimeColumn(DateColumn[ModelT]):
    format: str = "M j, Y, P"


@dataclass(slots=True)
class AvatarColumn(TextColumn[ModelT]):
    image: str | Callable[[ModelT], str | None] | None = None

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        base = super().get_cell(obj, resource, request)
        return Cell(
            display=base.display,
            kind="avatar",
            secondary=base.secondary,
            raw=base.raw,
        )


@dataclass(slots=True)
class TemplateColumn(Column[ModelT]):
    template_name: str = ""
    sortable: bool | str = False

    def get_cell(self, obj: ModelT, resource: ModelResource[ModelT], request: HttpRequest) -> Cell:
        html = render_to_string(
            self.template_name,
            {"object": obj, "resource": resource, "request": request},
            request=request,
        )
        return Cell(display=html, kind="html", raw=obj)


@dataclass(slots=True)
class ComputedColumn(Column[ModelT]):
    value: Callable[[ModelT], Any] | None = None
    sortable: bool | str = False

    def get_value(self, obj: ModelT, resource: ModelResource[ModelT]) -> Any:
        return self.value(obj) if self.value else super().get_value(obj, resource)


def infer_column(model: type[ModelT], accessor: str) -> Column[ModelT]:
    root = accessor.split("__", 1)[0]
    try:
        model_field = model._meta.get_field(root)
    except FieldDoesNotExist:
        return TextColumn(accessor)
    if isinstance(model_field, models.BooleanField):
        return BooleanColumn(accessor)
    if isinstance(model_field, models.DateTimeField):
        return DateTimeColumn(accessor)
    if isinstance(model_field, models.DateField):
        return DateColumn(accessor)
    if isinstance(model_field, (models.DecimalField, models.FloatField, models.IntegerField)):
        return NumberColumn(accessor)
    if model_field.is_relation:
        return RelationColumn(accessor)
    return TextColumn(accessor)
