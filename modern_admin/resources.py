from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import Q, QuerySet
from django.forms import modelform_factory
from django.http import HttpRequest
from django.utils.formats import date_format, number_format
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from modern_admin.actions import ResourceAction
from modern_admin.columns import Column, infer_column, resolve_value
from modern_admin.exceptions import InvalidResourceConfiguration
from modern_admin.filters import Filter, infer_filter, single_param
from modern_admin.navigation import Navigation
from modern_admin.permissions import PermissionPolicy
from modern_admin.queues import WorkQueue
from modern_admin.sections import DetailSection, DetailTab, RelatedObjectList
from modern_admin.widgets import Widget
from modern_admin.workflows import TransitionAction

if TYPE_CHECKING:
    from modern_admin.sites import ModernAdminSite

ModelT = TypeVar("ModelT", bound=models.Model)


class Resource:
    title: str = ""
    description: str = ""
    icon: str = "circle"
    navigation: Navigation | None = None
    permission_required: ClassVar[str | Sequence[str]] = ()
    template_name = ""
    site: ModernAdminSite
    key: str

    def get_permission_required(self, request: HttpRequest) -> tuple[str, ...]:
        required = self.permission_required
        return (required,) if isinstance(required, str) else tuple(required)

    def has_permission(self, request: HttpRequest) -> bool:
        """Navigation visibility and the endpoint guard share this single answer."""
        return bool(
            request.user.is_authenticated
            and request.user.has_perms(self.get_permission_required(request))
        )

    def get_context_data(self, request: HttpRequest, **kwargs: Any) -> dict[str, Any]:
        return kwargs


class ModelResource(Resource, Generic[ModelT]):
    model: type[ModelT]
    list_display: ClassVar[Sequence[str | Column[Any]]] = ()
    search_fields: ClassVar[Sequence[str]] = ()
    filters: ClassVar[Sequence[str | Filter[Any]]] = ()
    queues: ClassVar[Sequence[WorkQueue[Any]]] = ()
    ordering: ClassVar[Sequence[str]] = ()
    page_size = 25
    page_size_options: ClassVar[Sequence[int]] = (10, 25, 50, 100)
    form_class: type[forms.ModelForm[ModelT]] | None = None
    form_fields: ClassVar[Sequence[str] | str] = ()
    detail_sections: ClassVar[Sequence[DetailSection]] = ()
    # Computed detail fields have no verbose_name to translate; name them here.
    field_labels: ClassVar[Mapping[str, str]] = {}
    detail_tabs: ClassVar[Sequence[DetailTab | RelatedObjectList]] = ()
    actions: ClassVar[Sequence[type[ResourceAction[ModelT]] | ResourceAction[ModelT]]] = ()
    list_template_name = "modern_admin/pages/resource_list.html"
    detail_template_name = "modern_admin/pages/resource_detail.html"
    form_template_name = "modern_admin/pages/resource_form.html"
    permission_policy_class: type[PermissionPolicy[ModelT]] = PermissionPolicy

    def __init__(self, model: type[ModelT], site: ModernAdminSite) -> None:
        self.model = model
        self.site = site
        self.key = model._meta.model_name.replace("_", "-")
        self.title = self.title or capfirst(model._meta.verbose_name_plural)
        self.icon = self.icon or "database"
        self.navigation = self.navigation or Navigation(label=self.title, icon=self.icon)
        self.permission_policy = self.permission_policy_class(model)
        self._columns = tuple(self._bind_column(column) for column in self.list_display)
        if not self._columns:
            self._columns = (infer_column(model, "__str__").bind(model, self),)
        self._filters = tuple(self._bind_filter(filter_) for filter_ in self.filters)
        self._actions = tuple(self._bind_action(action) for action in self.actions)
        self.validate()

    def _bind_column(self, value: str | Column[Any]) -> Column[ModelT]:
        from copy import deepcopy

        column = infer_column(self.model, value) if isinstance(value, str) else deepcopy(value)
        return column.bind(self.model, self)

    def _bind_filter(self, value: str | Filter[Any]) -> Filter[ModelT]:
        from copy import deepcopy

        filter_ = infer_filter(self.model, value) if isinstance(value, str) else deepcopy(value)
        return filter_.bind(self.model, self)

    def _bind_action(
        self, action: type[ResourceAction[ModelT]] | ResourceAction[ModelT]
    ) -> ResourceAction[ModelT]:
        from copy import copy

        instance = action() if isinstance(action, type) else copy(action)
        instance.resource = self  # type: ignore[attr-defined]
        if isinstance(instance, TransitionAction):
            instance.validate_configuration(self.model)
        return instance

    def validate(self) -> None:
        tab_keys = [tab.key for tab in self.detail_tabs]
        if len(tab_keys) != len(set(tab_keys)) or "overview" in tab_keys:
            raise InvalidResourceConfiguration("Detail tab keys must be unique and not 'overview'.")
        for tab in self.detail_tabs:
            if isinstance(tab, RelatedObjectList) and not 1 <= tab.page_size <= 100:
                raise InvalidResourceConfiguration("RelatedObjectList page_size must be 1–100.")
        queue_keys = [queue.key for queue in self.queues]
        if len(queue_keys) != len(set(queue_keys)):
            raise InvalidResourceConfiguration(
                f"{self.__class__.__name__}.queues contains duplicate queue keys."
            )
        for path in self.search_fields:
            self._validate_field_path(path, "search_fields")
        available_ordering = {
            key for column in self._columns if (key := column.ordering_key) is not None
        }
        for value in self.ordering:
            if value.removeprefix("-") not in available_ordering:
                self._validate_field_path(value.removeprefix("-"), "ordering")
        action_keys = [action.key for action in self._actions]
        if len(set(action_keys)) != len(action_keys):
            raise InvalidResourceConfiguration(
                f"{self.__class__.__name__}.actions contains duplicate action keys."
            )

    def _validate_field_path(self, path: str, setting: str) -> None:
        model: type[models.Model] = self.model
        parts = path.split("__")
        for index, part in enumerate(parts):
            try:
                field_obj = model._meta.get_field(part)
            except FieldDoesNotExist as exc:
                raise InvalidResourceConfiguration(
                    f"{self.__class__.__name__}.{setting} references invalid field path '{path}'; "
                    f"{model.__name__} has no field '{part}'."
                ) from exc
            if index < len(parts) - 1:
                if not field_obj.is_relation or field_obj.related_model is None:
                    raise InvalidResourceConfiguration(
                        f"{self.__class__.__name__}.{setting} references '{path}', "
                        f"but '{part}' is not a relation."
                    )
                model = field_obj.related_model

    def get_queryset(self, request: HttpRequest) -> QuerySet[ModelT]:
        return self.model._default_manager.all()

    @property
    def verbose_name(self) -> str:
        return str(self.model._meta.verbose_name)

    @property
    def verbose_name_plural(self) -> str:
        return str(self.model._meta.verbose_name_plural)

    @property
    def app_verbose_name(self) -> str:
        return str(self.model._meta.app_config.verbose_name)

    def get_list_display(self, request: HttpRequest) -> tuple[Column[ModelT], ...]:
        return self._columns

    def get_filters(self, request: HttpRequest) -> tuple[Filter[ModelT], ...]:
        return self._filters

    def get_queues(self, request: HttpRequest) -> tuple[WorkQueue[ModelT], ...]:
        return tuple(queue for queue in self.queues if queue.has_permission(request))

    def get_actions(
        self,
        request: HttpRequest,
        placement: str | None = None,
        obj: ModelT | None = None,
    ) -> tuple[ResourceAction[ModelT], ...]:
        return tuple(
            action
            for action in self._actions
            if (placement is None or placement in action.placements)
            and action.has_permission(request, obj)
        )

    def get_action(self, key: str) -> ResourceAction[ModelT] | None:
        return next((action for action in self._actions if action.key == key), None)

    def get_search_fields(self, request: HttpRequest) -> Sequence[str]:
        return self.search_fields

    def search_queryset(
        self, request: HttpRequest, queryset: QuerySet[ModelT], query: str
    ) -> QuerySet[ModelT]:
        if not query or not self.get_search_fields(request):
            return queryset
        expression = Q()
        for field_name in self.get_search_fields(request):
            expression |= Q(**{f"{field_name}__icontains": query})
        queryset = queryset.filter(expression)
        if any("__" in name for name in self.get_search_fields(request)):
            queryset = queryset.distinct()
        return queryset

    def get_ordering(self, request: HttpRequest) -> Sequence[str]:
        return self.ordering

    def get_page_size(self, request: HttpRequest) -> int:
        try:
            requested = int(single_param(request.GET, "page_size", str(self.page_size)))
        except ValueError:
            return self.page_size
        return requested if requested in self.page_size_options else self.page_size

    @property
    def has_form(self) -> bool:
        return bool(
            self.form_class
            or self.form_fields
            or type(self).get_form_class is not ModelResource.get_form_class
        )

    def get_form_class(
        self, request: HttpRequest, obj: ModelT | None = None
    ) -> type[forms.ModelForm[ModelT]]:
        if self.form_class:
            return self.form_class
        return modelform_factory(self.model, fields=self.form_fields)

    def save_form(
        self,
        request: HttpRequest,
        form: forms.ModelForm[ModelT],
        *,
        change: bool,
    ) -> ModelT:
        return form.save()

    def get_detail_sections(self, request: HttpRequest, obj: ModelT) -> Sequence[DetailSection]:
        if self.detail_sections:
            return self.detail_sections
        field_names = tuple(
            field.name
            for field in self.model._meta.fields
            if field.name not in {"id", self.model._meta.pk.name}
        )
        return (DetailSection(title=_("Overview"), fields=field_names[:10]),)

    def get_detail_tabs(
        self, request: HttpRequest, obj: ModelT
    ) -> Sequence[DetailTab | RelatedObjectList]:
        return self.detail_tabs

    def get_object_label(self, obj: ModelT) -> str:
        return str(obj)

    def get_field_label(self, path: str) -> str:
        if path in self.field_labels:
            return str(self.field_labels[path])
        try:
            return capfirst(self.model._meta.get_field(path).verbose_name)
        except FieldDoesNotExist:
            return capfirst(path.replace("_", " "))

    def get_field_value(self, obj: ModelT, path: str) -> Any:
        if hasattr(self, path) and callable(getattr(self, path)):
            return getattr(self, path)(obj)
        return resolve_value(obj, path)

    def format_value(self, value: Any) -> str:
        if value in (None, ""):
            return "—"
        if isinstance(value, bool):
            return _("Yes") if value else _("No")
        if isinstance(value, models.Manager):
            # One extra row tells us whether the relation continues past the preview.
            labels = [str(item) for item in value.all()[:6]]
            if not labels:
                return "—"
            return ", ".join(labels[:5]) + (", …" if len(labels) > 5 else "")
        return str(value)

    def format_field_value(self, obj: ModelT, path: str, value: Any) -> str:
        display_method = getattr(obj, f"get_{path}_display", None)
        if callable(display_method):
            return str(display_method())
        if isinstance(value, datetime):
            return date_format(value, "DATETIME_FORMAT")
        if isinstance(value, date):
            return date_format(value, "DATE_FORMAT")
        if isinstance(value, Decimal):
            return str(number_format(value, decimal_pos=2, use_l10n=True, force_grouping=True))
        return self.format_value(value)

    def get_urls(self) -> Sequence[Any]:
        """Additional Django URL patterns mounted below this resource's list URL."""
        return ()


class PageResource(Resource):
    path = ""
    label = ""
    navigation: Navigation | None = None

    def __init__(self, site: ModernAdminSite) -> None:
        self.site = site
        self.key = self.path.strip("/").replace("/", "-") or self.__class__.__name__.lower()
        self.title = self.title or self.label or self.__class__.__name__.removesuffix("Page")

    def get_context_data(self, request: HttpRequest, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(request, page=self, **kwargs)


class Dashboard(PageResource):
    path = ""
    title = _("Overview")
    description = _("A live view of the work that needs attention.")
    template_name = "modern_admin/pages/dashboard.html"
    widgets: ClassVar[Sequence[Widget]] = ()

    def get_widgets(self, request: HttpRequest) -> Sequence[Widget]:
        return self.widgets
