from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models
from django.db.models import Q, QuerySet
from django.http import QueryDict
from django.utils.dateparse import parse_date
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from modern_admin.exceptions import InvalidResourceConfiguration, NotRegistered

if TYPE_CHECKING:
    from django.http import HttpRequest

    from modern_admin.resources import ModelResource

ModelT = TypeVar("ModelT", bound=models.Model)
ChoiceIterable = Iterable[tuple[Any, str]]


def single_param(params: QueryDict, key: str, default: str = "") -> str:
    """Return the last meaningful value for a single-valued query parameter.

    A form can legitimately serialise the same filter key more than once -- a
    hidden value carrier plus a no-JS fallback control, a drawer duplicating a
    toolbar field, or a stale key already present in the URL. ``QueryDict.get``
    answers with the *last* value, so a trailing ``&key=`` would silently
    discard the selection the user just made. Blank values never win here.
    """
    for value in reversed(params.getlist(key)):
        if value != "":
            return value
    return default


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
    autocomplete_url: str = ""


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
        self._bound_label = self.label or capfirst(model_field.verbose_name)
        return self

    @property
    def key(self) -> str:
        return self.parameter or self.accessor

    @property
    def heading(self) -> str:
        return self._bound_label or self.label or capfirst(self.accessor.replace("_", " "))

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        value = single_param(params, self.key)
        return queryset.filter(**{self.accessor: value}) if value else queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        value = single_param(params, self.key)
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
        value = single_param(params, self.key).strip()
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
        value = single_param(params, self.key)
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
        values = {value for value in params.getlist(self.key) if value}
        options = tuple(
            FilterOption(str(option_value), str(option_label), str(option_value) in values)
            for option_value, option_label in self._choices(request, resource)
        )
        labels = ", ".join(str(option.label) for option in options if option.selected)
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
    choices: ChoiceIterable | Callable[[HttpRequest], ChoiceIterable] | None = field(
        default_factory=lambda: (("1", _("Yes")), ("0", _("No")))
    )

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        value = single_param(params, self.key)
        if value not in {"0", "1"}:
            return queryset
        return queryset.filter(**{self.accessor: value == "1"})


@dataclass(slots=True)
class RelationFilter(ChoiceFilter[ModelT]):
    """Server-searched relation choices; limit is a page size, never a total cap."""

    choices: ChoiceIterable | Callable[[HttpRequest], ChoiceIterable] | None = None
    limit: int = 100
    search_fields: tuple[str, ...] = ()

    def bind(self, model: type[ModelT], resource: ModelResource[ModelT]) -> RelationFilter[ModelT]:
        Filter.bind(self, model, resource)
        if "__" in self.accessor:
            raise InvalidResourceConfiguration("RelationFilter accessor must be a direct relation.")
        relation = model._meta.get_field(self.accessor)
        if not relation.is_relation or relation.related_model is None or self.limit < 1:
            raise InvalidResourceConfiguration(
                "RelationFilter needs a relation and a positive limit."
            )
        for path in self.search_fields:
            target = relation.related_model
            try:
                for index, part in enumerate(path.split("__")):
                    target_field = target._meta.get_field(part)
                    if index < len(path.split("__")) - 1:
                        target = target_field.related_model
                        if target is None:
                            raise FieldDoesNotExist(path)
            except FieldDoesNotExist as exc:
                raise InvalidResourceConfiguration(
                    f"RelationFilter has an invalid search field: {path}."
                ) from exc
        return self

    def value_field(self, resource: ModelResource[ModelT]) -> str:
        relation = resource.model._meta.get_field(self.accessor)
        return relation.target_field.name if relation.many_to_one or relation.one_to_one else "pk"

    def option_value(self, obj: models.Model, resource: ModelResource[ModelT]) -> str:
        return str(getattr(obj, self.value_field(resource)))

    def can_view_option(self, request, resource, obj) -> bool:
        try:
            related = resource.site.registry.get_for_model(type(obj))
        except NotRegistered:
            return True
        return related.permission_policy.can_view(request.user, obj)

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        try:
            return Filter.apply(self, queryset, params).distinct()
        except (ValidationError, ValueError, TypeError):
            return queryset.none()

    def get_queryset(self, request: HttpRequest, resource: ModelResource[ModelT]) -> QuerySet[Any]:
        relation = resource.model._meta.get_field(self.accessor)
        try:
            related = resource.site.registry.get_for_model(relation.related_model)
        except NotRegistered:
            # Unregistered models are limited to relations visible in this resource.
            return relation.related_model._default_manager.filter(
                **{
                    f"{self.value_field(resource)}__in": resource.get_queryset(request).values(
                        self.accessor
                    )
                }
            )
        if not related.has_permission(request) or not related.permission_policy.can_view(
            request.user
        ):
            return related.model._default_manager.none()
        return related.get_queryset(request)

    def search(
        self, request: HttpRequest, resource: ModelResource[ModelT], query: str
    ) -> QuerySet[Any]:
        queryset = self.get_queryset(request, resource)
        if query:
            fields = self.search_fields
            if not fields:
                with suppress(NotRegistered):
                    related = resource.site.registry.get_for_model(queryset.model)
                    fields = tuple(related.get_search_fields(request))
            fields = fields or tuple(
                f.name
                for f in queryset.model._meta.fields
                if isinstance(f, (models.CharField, models.TextField))
            )
            condition = Q()
            for name in fields:
                condition |= Q(**{f"{name}__icontains": query})
            with suppress(ValidationError, ValueError, TypeError):
                condition |= Q(pk=queryset.model._meta.pk.to_python(query))
            queryset = queryset.filter(condition) if condition else queryset.none()
        return queryset.order_by("pk").distinct()

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        if self.choices is not None:
            return ChoiceFilter.get_state(self, request, resource, params)
        value = single_param(params, self.key)
        selected = None
        if value:
            with suppress(ValidationError, ValueError, TypeError):
                selected = (
                    self.get_queryset(request, resource)
                    .filter(**{self.value_field(resource): value})
                    .first()
                )
                if selected is not None and not self.can_view_option(request, resource, selected):
                    selected = None
        label = str(selected) if selected is not None else value
        return FilterState(
            key=self.key,
            label=self.heading,
            kind="relation",
            value=value,
            options=(FilterOption(value, label, True),) if value else (),
            active_label=f"{self.heading}: {label}" if value else "",
            autocomplete_url=resource.site.reverse(
                f"{resource.key}_filter_choices", args=(self.key,)
            ),
        )


@dataclass(slots=True)
class DateFilter(Filter[ModelT]):
    _is_datetime: bool = field(default=False, init=False, repr=False)

    def bind(self, model: type[ModelT], resource: ModelResource[ModelT]) -> DateFilter[ModelT]:
        Filter.bind(self, model, resource)
        self._is_datetime = isinstance(
            model._meta.get_field(self.accessor.split("__", 1)[0]), models.DateTimeField
        )
        return self

    def apply(self, queryset: QuerySet[ModelT], params: QueryDict) -> QuerySet[ModelT]:
        raw = single_param(params, self.key)
        value = parse_date(raw)
        lookup = f"{self.accessor}__date" if self._is_datetime else self.accessor
        return queryset.filter(**{lookup: value}) if value else queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        value = single_param(params, self.key)
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
        Filter.bind(self, model, resource)
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
        start = parse_date(single_param(params, self.from_key))
        end = parse_date(single_param(params, self.to_key))
        base = f"{self.accessor}__date" if self._is_datetime else self.accessor
        if start:
            queryset = queryset.filter(**{f"{base}__gte": start})
        if end:
            queryset = queryset.filter(**{f"{base}__lte": end})
        return queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        start = single_param(params, self.from_key)
        end = single_param(params, self.to_key)
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
        raw = single_param(params, self.key)
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
                value = Decimal(single_param(params, key))
            except (InvalidOperation, TypeError):
                continue
            queryset = queryset.filter(**{f"{self.accessor}__{suffix}": value})
        return queryset

    def get_state(
        self, request: HttpRequest, resource: ModelResource[ModelT], params: QueryDict
    ) -> FilterState:
        start = single_param(params, self.from_key)
        end = single_param(params, self.to_key)
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
