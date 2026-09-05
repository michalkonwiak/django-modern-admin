from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import QuerySet
from django.http import QueryDict
from django.utils.dateparse import parse_date
from django.utils.text import capfirst

from modern_admin.exceptions import InvalidResourceConfiguration

if TYPE_CHECKING:
    from django.http import HttpRequest

    from modern_admin.resources import ModelResource

ModelT = TypeVar("ModelT", bound=models.Model)
ChoiceIterable = Iterable[tuple[Any, str]]


@dataclass(frozen=True, slots=True)
class FilterOption:
    value: str
    label: str
    selected: bool = False


@dataclass(frozen=True, slots=True)
class FilterState:
    key: str
    label: str
    kind: str
    options: tuple[FilterOption, ...] = ()
    value: str = ""
    value_to: str = ""
    active_label: str = ""


@dataclass(slots=True)
class Filter(Generic[ModelT]):
    accessor: str
    label: str | None = None
    parameter: str | None = None
    _bound_label: str = field(default="", init=False, repr=False)

    def bind(self, model: type[ModelT], resource: ModelResource[ModelT]) -> Filter[ModelT]:
        root = self.accessor.split("__", 1)[0]
        try:
            model_field = model._meta.get_field(root)
        except FieldDoesNotExist as exc:
            raise InvalidResourceConfiguration(
                f"{resource.__class__.__name__}.filters references '{self.accessor}', "
                f"but {model.__name__} has no field named '{root}'."
            ) from exc
        self._bound_label = self.label or capfirst(str(model_field.verbose_name))
        return self

    @property
    def key(self) -> str:
        return self.parameter or self.accessor

    @property
    def heading(self) -> str:
        return self._bound_label or self.label or capfirst(self.accessor.replace("_", " "))

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        value = params.get(self.key)
        return queryset.filter(**{self.accessor: value}) if value not in (None, "") else queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        value = params.get(self.key, "")
        return FilterState(
            key=self.key,
            label=self.heading,
            kind="text",
            value=value,
            active_label=f"{self.heading}: {value}" if value else "",
        )


@dataclass(slots=True)
class TextFilter(Filter[ModelT]):
    lookup: str = "icontains"

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        value = params.get(self.key, "").strip()
        return queryset.filter(**{f"{self.accessor}__{self.lookup}": value}) if value else queryset


@dataclass(slots=True)
class ChoiceFilter(Filter[ModelT]):
    choices: ChoiceIterable | Callable[[HttpRequest], ChoiceIterable] | None = None

    def _choices(self, request: HttpRequest, resource: ModelResource[ModelT]) -> ChoiceIterable:
        if callable(self.choices):
            return self.choices(request)
        if self.choices is not None:
            return self.choices
        field_obj = resource.model._meta.get_field(self.accessor.split("__", 1)[0])
        return field_obj.choices

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        value = params.get(self.key, "")
        options = tuple(
            FilterOption(str(option_value), str(option_label), str(option_value) == value)
            for option_value, option_label in self._choices(request, resource)
        )
        active = next((option.label for option in options if option.selected), "")
        return FilterState(
            key=self.key,
            label=self.heading,
            kind="choice",
            options=options,
            value=value,
            active_label=f"{self.heading}: {active}" if active else "",
        )


@dataclass(slots=True)
class MultipleChoiceFilter(ChoiceFilter[ModelT]):
    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        values = [value for value in params.getlist(self.key) if value]
        return queryset.filter(**{f"{self.accessor}__in": values}) if values else queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        values = set(params.getlist(self.key))
        options = tuple(
            FilterOption(str(option_value), str(option_label), str(option_value) in values)
            for option_value, option_label in self._choices(request, resource)
        )
        labels = ", ".join(option.label for option in options if option.selected)
        return FilterState(
            key=self.key,
            label=self.heading,
            kind="multiple_choice",
            options=options,
            value=",".join(values),
            active_label=f"{self.heading}: {labels}" if labels else "",
        )


@dataclass(slots=True)
class BooleanFilter(ChoiceFilter[ModelT]):
    choices: ChoiceIterable | Callable[[HttpRequest], ChoiceIterable] | None = (
        ("1", "Yes"),
        ("0", "No"),
    )

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        value = params.get(self.key, "")
        if value not in {"0", "1"}:
            return queryset
        return queryset.filter(**{self.accessor: value == "1"})


@dataclass(slots=True)
class RelationFilter(ChoiceFilter[ModelT]):
    choices: ChoiceIterable | Callable[[HttpRequest], ChoiceIterable] | None = None
    limit: int = 100

    def _choices(self, request: HttpRequest, resource: ModelResource[ModelT]) -> ChoiceIterable:
        if self.choices is not None:
            return super()._choices(request, resource)
        field_obj = resource.model._meta.get_field(self.accessor.split("__", 1)[0])
        related_model = field_obj.related_model
        return ((obj.pk, str(obj)) for obj in related_model._default_manager.all()[: self.limit])


@dataclass(slots=True)
class DateFilter(Filter[ModelT]):
    _is_datetime: bool = field(default=False, init=False, repr=False)

    def bind(self, model: type[ModelT], resource: ModelResource[ModelT]) -> DateFilter[ModelT]:
        super().bind(model, resource)
        self._is_datetime = isinstance(
            model._meta.get_field(self.accessor.split("__", 1)[0]), models.DateTimeField
        )
        return self

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        raw = params.get(self.key, "")
        value = parse_date(raw)
        lookup = f"{self.accessor}__date" if self._is_datetime else self.accessor
        return queryset.filter(**{lookup: value}) if value else queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        value = params.get(self.key, "")
        return FilterState(
            key=self.key,
            label=self.heading,
            kind="date",
            value=value,
            active_label=f"{self.heading}: {value}" if value else "",
        )


@dataclass(slots=True)
class DateRangeFilter(Filter[ModelT]):
    _is_datetime: bool = field(default=False, init=False, repr=False)

    def bind(self, model: type[ModelT], resource: ModelResource[ModelT]) -> DateRangeFilter[ModelT]:
        super().bind(model, resource)
        self._is_datetime = isinstance(
            model._meta.get_field(self.accessor.split("__", 1)[0]), models.DateTimeField
        )
        return self

    @property
    def from_key(self) -> str:
        return f"{self.key}__gte"

    @property
    def to_key(self) -> str:
        return f"{self.key}__lte"

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        start = parse_date(params.get(self.from_key, ""))
        end = parse_date(params.get(self.to_key, ""))
        base = f"{self.accessor}__date" if self._is_datetime else self.accessor
        if start:
            queryset = queryset.filter(**{f"{base}__gte": start})
        if end:
            queryset = queryset.filter(**{f"{base}__lte": end})
        return queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        start = params.get(self.from_key, "")
        end = params.get(self.to_key, "")
        value = " – ".join(part for part in (start, end) if part)
        return FilterState(
            key=self.key,
            label=self.heading,
            kind="date_range",
            value=start,
            value_to=end,
            active_label=f"{self.heading}: {value}" if value else "",
        )


@dataclass(slots=True)
class NumberFilter(Filter[ModelT]):
    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        raw = params.get(self.key, "")
        try:
            value = Decimal(raw)
        except (InvalidOperation, TypeError):
            return queryset
        return queryset.filter(**{self.accessor: value})


@dataclass(slots=True)
class NumberRangeFilter(Filter[ModelT]):
    @property
    def from_key(self) -> str:
        return f"{self.key}__gte"

    @property
    def to_key(self) -> str:
        return f"{self.key}__lte"

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        for suffix, key in (("gte", self.from_key), ("lte", self.to_key)):
            try:
                value = Decimal(params.get(key, ""))
            except (InvalidOperation, TypeError):
                continue
            queryset = queryset.filter(**{f"{self.accessor}__{suffix}": value})
        return queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        start = params.get(self.from_key, "")
        end = params.get(self.to_key, "")
        value = " – ".join(part for part in (start, end) if part)
        return FilterState(
            key=self.key,
            label=self.heading,
            kind="number_range",
            value=start,
            value_to=end,
            active_label=f"{self.heading}: {value}" if value else "",
        )


def infer_filter(model: type[ModelT], accessor: str) -> Filter[ModelT]:
    field_obj = model._meta.get_field(accessor.split("__", 1)[0])
    if field_obj.choices:
        return ChoiceFilter(accessor)
    if isinstance(field_obj, models.BooleanField):
        return BooleanFilter(accessor)
    if isinstance(field_obj, models.DateField):
        return DateRangeFilter(accessor)
    if field_obj.is_relation:
        return RelationFilter(accessor)
    if isinstance(field_obj, (models.IntegerField, models.FloatField, models.DecimalField)):
        return NumberRangeFilter(accessor)
    return TextFilter(accessor)
