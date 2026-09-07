from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models, router, transaction
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
    QueryDict,
)
from django.shortcuts import get_object_or_404, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from modern_admin.audit import action_label, events_for, record_event
from modern_admin.columns import Cell, Column
from modern_admin.filters import RelationFilter
from modern_admin.forms.widgets import AccessChecklist
from modern_admin.models import SavedView
from modern_admin.resources import ModelResource
from modern_admin.responses import Toast, htmx_events, is_htmx, notify
from modern_admin.sections import RelatedObjectList
from modern_admin.sites import ModernAdminSite


@dataclass(frozen=True, slots=True)
class TableRow:
    obj: models.Model
    cells: tuple[tuple[Column[Any], Cell], ...]
    detail_url: str
    actions: tuple[ActionLink, ...]
    preview_url: str = ""


@dataclass(frozen=True, slots=True)
class ActionLink:
    action: Any
    url: str
    unavailable_reason: str = ""


@dataclass(frozen=True, slots=True)
class DetailValue:
    label: str
    value: str
    raw: Any
    kind: str = "text"
    variant: str = "neutral"


def _guard(request: HttpRequest) -> HttpResponse | None:
    if request.user.is_authenticated:
        return None
    return redirect_to_login(request.get_full_path())


def _permission_denied(
    request: HttpRequest,
    site: ModernAdminSite,
    message: str = _("You do not have access to this page."),
) -> HttpResponse:
    template = (
        "modern_admin/partials/error_state.html"
        if is_htmx(request)
        else "modern_admin/pages/error.html"
    )
    context = site.each_context(request) | {
        "status": 403,
        "title": _("Access restricted"),
        "message": message,
        "breadcrumbs": ((_("Access restricted"), ""),),
    }
    return render(request, template, context, status=403)


def _first_permitted_destination(request: HttpRequest, site: ModernAdminSite) -> HttpResponse:
    """Operators without dashboard access land on their first permitted page."""
    for group in site.get_navigation(request).values():
        for item in group:
            return HttpResponseRedirect(item.url)
    return _permission_denied(request, site, _("You do not have access to any workspace page."))


def _site_context(site: ModernAdminSite, request: HttpRequest, **context: Any) -> dict[str, Any]:
    return site.each_context(request) | context


def _canonical_params(params: QueryDict) -> QueryDict:
    """Collapse repeated keys down to their meaningful values.

    A repeated key with a blank trailing value would otherwise be carried into
    every pagination, sort and saved-view link, where ``QueryDict.get`` reads the
    blank and the filter looks like it was never applied. See
    ``modern_admin.filters.single_param``.
    """
    clean = params.copy()
    for key in params:
        values = params.getlist(key)
        if len(values) > 1:
            meaningful = [value for value in values if value != ""]
            clean.setlist(key, meaningful or [""])
    return clean


def _query_url(request: HttpRequest, **changes: str | int | None) -> str:
    params = _canonical_params(request.GET)
    params.pop("fragment", None)
    for key, value in changes.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    encoded = params.urlencode()
    return f"{request.path}?{encoded}" if encoded else request.path


def _list_context(
    request: HttpRequest,
    site: ModernAdminSite,
    resource: ModelResource[Any],
) -> dict[str, Any]:
    queryset = resource.get_queryset(request)
    queues = resource.get_queues(request)
    queue_key = request.GET.get("queue", "")
    selected_queue = next((queue for queue in queues if queue.key == queue_key), None)
    if queue_key and selected_queue is None:
        raise Http404(_("Unknown or unavailable work queue"))
    # Counts describe the scoped workload, not the current search result.
    queue_conditions = {queue.key: queue.get_condition(request) for queue in queues}
    counts = (
        queryset.aggregate(
            **{
                f"queue_{index}": models.Count(
                    "pk", filter=queue_conditions[queue.key], distinct=True
                )
                for index, queue in enumerate(queues)
            }
        )
        if queues
        else {}
    )
    queue_links = tuple(
        {
            "label": queue.label,
            "count": counts[f"queue_{index}"],
            "url": _query_url(request, queue=queue.key, page=None),
            "active": queue.key == queue_key,
        }
        for index, queue in enumerate(queues)
    )
    if selected_queue:
        queryset = queryset.filter(queue_conditions[queue_key]).distinct()
    query = request.GET.get("q", "").strip()
    queryset = resource.search_queryset(request, queryset, query)
    filters = resource.get_filters(request)
    for filter_ in filters:
        queryset = filter_.apply(queryset, request.GET)

    columns = resource.get_list_display(request)
    available_ordering = {
        column.ordering_key: column for column in columns if column.ordering_key is not None
    }
    requested_ordering = request.GET.get("ordering", "")
    ordering_name = requested_ordering.removeprefix("-")
    if ordering_name in available_ordering:
        queryset = queryset.order_by(requested_ordering, "pk")
        applied_ordering = requested_ordering
    else:
        default_ordering = tuple(resource.get_ordering(request))
        queryset = queryset.order_by(*default_ordering, "pk") if default_ordering else queryset
        if not queryset.ordered:
            queryset = queryset.order_by("pk")
        applied_ordering = default_ordering[0] if default_ordering else ""

    page_size = resource.get_page_size(request)
    paginator = Paginator(queryset, page_size)
    page = paginator.get_page(request.GET.get("page", 1))
    rows: list[TableRow] = []
    for obj in page.object_list:
        detail_url = site.reverse(f"{resource.key}_detail", args=(obj.pk,))
        rows.append(
            TableRow(
                obj=obj,
                cells=tuple(
                    (column, column.get_cell(obj, resource, request)) for column in columns
                ),
                detail_url=detail_url,
                preview_url=f"{detail_url}?surface=preview",
                actions=tuple(
                    ActionLink(
                        action=action,
                        url=site.reverse(f"{resource.key}_action", args=(obj.pk, action.key)),
                    )
                    for action in resource.get_actions(request, "row", obj)
                ),
            )
        )

    column_headers = []
    for index, column in enumerate(columns):
        key = column.ordering_key
        if not key:
            sort_url = ""
            direction = ""
        elif applied_ordering == key:
            sort_url = _query_url(request, ordering=f"-{key}", page=None)
            direction = "asc"
        elif applied_ordering == f"-{key}":
            sort_url = _query_url(request, ordering=key, page=None)
            direction = "desc"
        else:
            sort_url = _query_url(request, ordering=key, page=None)
            direction = ""
        column_headers.append(
            {
                "column": column,
                "sort_url": sort_url,
                "direction": direction,
                "numeric": bool(rows and rows[0].cells[index][1].numeric),
                "is_status": bool(rows and rows[0].cells[index][1].kind == "badge"),
            }
        )

    filter_states = tuple(filter_.get_state(request, resource, request.GET) for filter_ in filters)
    active_filters = tuple(state for state in filter_states if state.active_label)
    create_url = site.reverse(f"{resource.key}_create")
    saved_params = _canonical_params(request.GET)
    saved_params.pop("page", None)
    saved_params.pop("fragment", None)
    current_view_query = saved_params.urlencode()
    return _site_context(
        site,
        request,
        resource=resource,
        queue_links=queue_links,
        selected_queue=selected_queue,
        all_queue_url=_query_url(request, queue=None, page=None),
        columns=columns,
        column_headers=column_headers,
        rows=rows,
        page=page,
        paginator=paginator,
        page_links=[
            {"number": number, "url": _query_url(request, page=number)}
            for number in paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
            if isinstance(number, int)
        ],
        has_page_gap=paginator.num_pages > 5,
        previous_url=_query_url(request, page=page.previous_page_number())
        if page.has_previous()
        else "",
        next_url=_query_url(request, page=page.next_page_number()) if page.has_next() else "",
        query=query,
        filter_states=filter_states,
        active_filters=active_filters,
        clear_filters_url=f"{request.path}?{urlencode({'queue': queue_key})}"
        if queue_key
        else request.path,
        clear_search_url=_query_url(request, q=None, page=None),
        applied_ordering=applied_ordering,
        create_url=create_url,
        can_add=resource.has_form and resource.permission_policy.can_add(request.user),
        bulk_actions=tuple(
            ActionLink(
                action=action,
                url=site.reverse(f"{resource.key}_bulk_action", args=(action.key,)),
            )
            for action in resource.get_actions(request, "bulk")
        ),
        page_size=page_size,
        page_size_options=resource.page_size_options,
        saved_views=tuple(
            {
                "name": saved.name,
                "url": f"{request.path}?{saved.query_string}",
            }
            for saved in SavedView.objects.filter(
                user=request.user,
                site_name=site.name,
                resource_key=resource.key,
            )
        ),
        current_view_query=current_view_query,
        save_view_url=(
            site.reverse(f"{resource.key}_save_view")
            + "?"
            + urlencode({"query": current_view_query})
        ),
        breadcrumbs=((_("Overview"), site.reverse("dashboard")), (resource.title, "")),
    )


def resource_list_view(
    request: HttpRequest,
    *,
    site: ModernAdminSite,
    resource_key: str,
) -> HttpResponse:
    if response := _guard(request):
        return response
    resource = site.get_resource(resource_key)
    if not resource.permission_policy.can_view(request.user):
        return _permission_denied(request, site)
    context = _list_context(request, site, resource)
    if is_htmx(request):
        return render(request, "modern_admin/partials/resource_panel.html", context)
    return render(request, resource.list_template_name, context)


class SavedViewForm(forms.Form):
    name = forms.CharField(max_length=100, label=_("View name"))
    query = forms.CharField(max_length=2000, widget=forms.HiddenInput)


def saved_view_view(
    request: HttpRequest,
    *,
    site: ModernAdminSite,
    resource_key: str,
) -> HttpResponse:
    if response := _guard(request):
        return response
    resource = site.get_resource(resource_key)
    if not resource.permission_policy.can_view(request.user):
        return _permission_denied(request, site)
    form = SavedViewForm(
        data=request.POST or None,
        initial={"query": request.GET.get("query", "")},
    )
    _style_form(form)
    if request.method == "POST" and form.is_valid():
        raw_params = QueryDict(form.cleaned_data["query"])
        allowed = {"q", "ordering", "page_size", "columns", "queue"}
        for filter_ in resource.get_filters(request):
            allowed.update(
                {
                    filter_.key,
                    f"{filter_.key}__gte",
                    f"{filter_.key}__lte",
                }
            )
        canonical = QueryDict(mutable=True)
        for key in allowed:
            for value in raw_params.getlist(key):
                if value:
                    canonical.appendlist(key, value)
        SavedView.objects.update_or_create(
            user=request.user,
            site_name=site.name,
            resource_key=resource.key,
            name=form.cleaned_data["name"],
            defaults={"query_string": canonical.urlencode()},
        )
        message = _("Saved view “%(name)s”.") % {"name": form.cleaned_data["name"]}
        if is_htmx(request):
            return htmx_events(
                HttpResponse(status=204),
                toast=Toast(message),
                close_dialog=True,
                refresh=("#resource-panel",),
            )
        messages.success(request, message)
        suffix = f"?{canonical.urlencode()}" if canonical else ""
        return HttpResponseRedirect(site.reverse(f"{resource.key}_list") + suffix)
    context = _site_context(
        site,
        request,
        resource=resource,
        form=form,
        breadcrumbs=(
            (_("Overview"), site.reverse("dashboard")),
            (resource.title, site.reverse(f"{resource.key}_list")),
            (_("Save view"), ""),
        ),
    )
    template_name = (
        "modern_admin/partials/saved_view_dialog.html"
        if is_htmx(request)
        else "modern_admin/pages/saved_view.html"
    )
    response = render(request, template_name, context)
    if request.method == "POST" and form.errors:
        response.status_code = 422
    return response


def _labelled_events(resource: ModelResource, obj: models.Model) -> list[Any]:
    """Attach a display verb to each event: resource actions carry their label."""
    events = list(events_for(obj)[:20])
    for event in events:
        action = resource.get_action(event.action)
        event.display_action = action.label if action else action_label(event.action)
    return events


def resource_detail_view(
    request: HttpRequest,
    *,
    site: ModernAdminSite,
    resource_key: str,
    object_id: str,
) -> HttpResponse:
    if response := _guard(request):
        return response
    resource = site.get_resource(resource_key)
    obj = get_object_or_404(resource.get_queryset(request), pk=object_id)
    if not resource.permission_policy.can_view(request.user, obj):
        return _permission_denied(request, site)
    sections = []
    detail_columns = {column.accessor: column for column in resource.get_list_display(request)}
    for section in resource.get_detail_sections(request, obj):
        values = []
        for field_name in section.fields:
            raw = resource.get_field_value(obj, field_name)
            column = detail_columns.get(field_name)
            if column:
                cell = column.get_cell(obj, resource, request)
                values.append(
                    DetailValue(
                        label=resource.get_field_label(field_name),
                        value=cell.display,
                        raw=raw,
                        kind=cell.kind,
                        variant=cell.variant,
                    )
                )
            else:
                values.append(
                    DetailValue(
                        label=resource.get_field_label(field_name),
                        value=resource.format_field_value(obj, field_name, raw),
                        raw=raw,
                    )
                )
        values = tuple(values)
        sections.append((section, values))
    tabs = tuple(resource.get_detail_tabs(request, obj))
    preview = is_htmx(request) and request.GET.get("surface") == "preview"
    selected_tab_key = "" if preview else request.GET.get("tab", "")
    initial_tab = next((tab for tab in tabs if tab.key == selected_tab_key), None)
    initial_tab_context: dict[str, Any] = {}
    if initial_tab:
        initial_tab_context.update(_detail_tab_context(request, resource, obj, initial_tab))
    context = _site_context(
        site,
        request,
        resource=resource,
        object=obj,
        object_label=resource.get_object_label(obj),
        sections=sections,
        tabs=tabs,
        initial_tab=initial_tab,
        active_tab_key=initial_tab.key if initial_tab else "overview",
        detail_actions=tuple(
            ActionLink(
                action=action,
                url=site.reverse(f"{resource.key}_action", args=(obj.pk, action.key)),
                unavailable_reason=action.get_unavailable_reason(request, obj),
            )
            for action in resource.get_actions(request, "detail", obj)
        ),
        can_change=resource.has_form and resource.permission_policy.can_change(request.user, obj),
        edit_url=site.reverse(f"{resource.key}_edit", args=(obj.pk,)),
        list_url=site.reverse(f"{resource.key}_list"),
        detail_url=site.reverse(f"{resource.key}_detail", args=(obj.pk,)),
        audit_events=_labelled_events(resource, obj),
        breadcrumbs=(
            (_("Overview"), site.reverse("dashboard")),
            (resource.title, site.reverse(f"{resource.key}_list")),
            (resource.get_object_label(obj), ""),
        ),
    )
    context.update(initial_tab_context)
    context = resource.get_context_data(request, **context)
    if preview:
        template = (
            "modern_admin/partials/record_preview_body.html"
            if request.GET.get("fragment") == "preview"
            else "modern_admin/partials/record_preview.html"
        )
        return render(request, template, context)
    if is_htmx(request) and request.GET.get("fragment") == "detail":
        return render(request, "modern_admin/partials/resource_detail_body.html", context)
    return render(request, resource.detail_template_name, context)


# Subclasses must inherit their base widget's styling, so match by type, not name.
_CHECKBOX_WIDGETS = (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)
_TEXT_WIDGETS = (
    forms.TextInput,
    forms.NumberInput,
    forms.EmailInput,
    forms.URLInput,
    forms.PasswordInput,
    forms.Textarea,
)


def _style_form(form: Any) -> None:
    for field in form.fields.values():
        widget = field.widget
        if widget.is_hidden:
            continue
        if isinstance(widget, _CHECKBOX_WIDGETS):
            classes = "ma-checkbox"
        elif isinstance(widget, forms.Textarea):
            classes = "ma-input ma-textarea"
        else:
            classes = "ma-input"
        current = widget.attrs.get("class", "")
        widget.attrs["class"] = " ".join(dict.fromkeys(f"{current} {classes}".split()))
        if isinstance(widget, _TEXT_WIDGETS):
            widget.attrs.setdefault("placeholder", field.label)
        if isinstance(widget, AccessChecklist):
            # The field label lives outside the widget; name the option group for it.
            widget.group_label = str(field.label)


def resource_form_view(
    request: HttpRequest,
    *,
    site: ModernAdminSite,
    resource_key: str,
    object_id: str | None = None,
) -> HttpResponse:
    if response := _guard(request):
        return response
    resource = site.get_resource(resource_key)
    obj = get_object_or_404(resource.get_queryset(request), pk=object_id) if object_id else None
    allowed = (
        resource.permission_policy.can_change(request.user, obj)
        if obj
        else resource.permission_policy.can_add(request.user)
    )
    if not allowed:
        return _permission_denied(request, site)
    if not resource.has_form:
        raise Http404(_("Forms are not configured for this resource."))
    form_class = resource.get_form_class(request, obj)
    form = form_class(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=obj,
    )
    _style_form(form)
    dialog = (
        is_htmx(request)
        or request.GET.get("surface") == "dialog"
        or request.POST.get("surface") == "dialog"
    )
    if request.method == "POST" and form.is_valid():
        using = router.db_for_write(resource.model, instance=form.instance)
        with transaction.atomic(using=using):
            saved = resource.save_form(request, form, change=obj is not None)
            action_name = "updated" if obj else "created"
            record_event(request=request, action=action_name, obj=saved)
        message = (
            _("%(model)s updated successfully.") if obj else _("%(model)s created successfully.")
        ) % {"model": capfirst(resource.model._meta.verbose_name)}
        detail_url = site.reverse(f"{resource.key}_detail", args=(saved.pk,))
        if is_htmx(request):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = detail_url
            return htmx_events(response, toast=Toast(message), close_dialog=True)
        messages.success(request, message)
        return HttpResponseRedirect(detail_url)
    context = _site_context(
        site,
        request,
        resource=resource,
        object=obj,
        form=form,
        dialog=dialog,
        page_title=_("Edit %(object)s") % {"object": resource.get_object_label(obj)}
        if obj
        else _("New %(model)s") % {"model": resource.model._meta.verbose_name},
        submit_label=_("Save changes")
        if obj
        else _("Create %(model)s") % {"model": resource.model._meta.verbose_name},
        cancel_url=(
            site.reverse(f"{resource.key}_detail", args=(obj.pk,))
            if obj
            else site.reverse(f"{resource.key}_list")
        ),
        breadcrumbs=(
            (_("Overview"), site.reverse("dashboard")),
            (resource.title, site.reverse(f"{resource.key}_list")),
            (_("Edit") if obj else _("New"), ""),
        ),
    )
    if dialog:
        response = render(request, "modern_admin/partials/form_dialog.html", context)
    else:
        response = render(request, resource.form_template_name, context)
    if request.method == "POST" and form.errors and is_htmx(request):
        response.status_code = 422
    return response


def _lock_action_rows(queryset: models.QuerySet) -> None:
    # Lock only base rows: PostgreSQL forbids FOR UPDATE on DISTINCT/GROUP BY
    # queries. Keep the scoped selection in a subquery, and acquire bulk locks
    # in primary-key order to avoid inconsistent ordering between operators.
    rows = (
        queryset.model._base_manager.using(queryset.db)
        .filter(pk__in=queryset.order_by().values("pk"))
        .order_by("pk")
        .select_for_update()
    )
    list(rows.values_list("pk", flat=True))


def action_view(
    request: HttpRequest,
    *,
    site: ModernAdminSite,
    resource_key: str,
    action_key: str,
    object_id: str | None,
) -> HttpResponse:
    if response := _guard(request):
        return response
    resource = site.get_resource(resource_key)
    action = resource.get_action(action_key)
    if action is None:
        raise Http404(_("Unknown resource action"))
    placements = {"row", "detail"} if object_id is not None else {"bulk", "resource"}
    if not placements.intersection(action.placements):
        raise Http404(_("Action is not available at this endpoint"))
    obj = get_object_or_404(resource.get_queryset(request), pk=object_id) if object_id else None
    if not action.has_permission(request, obj):
        return _permission_denied(request, site, _("You cannot run this action."))
    form = action.get_form_class()(**action.get_form_kwargs(request=request, obj=obj))
    _style_form(form)
    if request.method == "POST" and form.is_valid():
        try:
            with (
                transaction.atomic(using=resource.get_queryset(request).db)
                if action.atomic
                else nullcontext()
            ):
                if obj is not None:
                    # Re-fetch inside the transaction: never execute against the object
                    # loaded before a concurrent operator committed their action.
                    execution_queryset = resource.get_queryset(request)
                    if action.atomic:
                        _lock_action_rows(execution_queryset.filter(pk=object_id))
                    obj = get_object_or_404(execution_queryset, pk=object_id)
                    if not action.has_permission(request, obj):
                        return _permission_denied(request, site, _("You cannot run this action."))
                    action.validate_execution(request, obj)
                    result = action.execute(
                        request=request, obj=obj, cleaned_data=form.cleaned_data
                    )
                    record_event(request=request, action=action.key, obj=obj)
                else:
                    selected = request.POST.getlist("selected")
                    if not selected or len(selected) > 1000:
                        raise ValidationError(_("Select between 1 and 1,000 records."))
                    queryset = resource.get_queryset(request).filter(pk__in=selected)
                    if action.atomic:
                        _lock_action_rows(queryset)
                    objects = list(queryset)
                    if len(objects) != len(set(selected)) or any(
                        not action.has_permission(request, item) for item in objects
                    ):
                        return _permission_denied(request, site, _("Selection is not permitted."))
                    for item in objects:
                        action.validate_execution(request, item)
                    result = action.execute_bulk(
                        request=request, queryset=queryset, cleaned_data=form.cleaned_data
                    )
                if result.redirect_url and not url_has_allowed_host_and_scheme(
                    result.redirect_url,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    raise ValidationError(_("The action returned an unsafe redirect URL."))
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if is_htmx(request):
                response = HttpResponse(status=204)
                if result.redirect_url:
                    response["HX-Redirect"] = result.redirect_url
                return htmx_events(
                    response,
                    toast=Toast(result.message, result.level),
                    close_dialog=True,
                    refresh=tuple(
                        dict.fromkeys((*result.refresh, "#record-preview", "#related-list"))
                    )
                    if obj is not None
                    else result.refresh,
                )
            notify(request, Toast(result.message, result.level))
            fallback = (
                site.reverse(f"{resource.key}_detail", args=(obj.pk,))
                if obj
                else site.reverse(f"{resource.key}_list")
            )
            return HttpResponseRedirect(result.redirect_url or fallback)
    context = _site_context(
        site,
        request,
        resource=resource,
        object=obj,
        action=action,
        unavailable_reason=action.get_unavailable_reason(request, obj),
        form=form,
        selected=request.GET.getlist("selected") or request.POST.getlist("selected"),
        breadcrumbs=(
            (_("Overview"), site.reverse("dashboard")),
            (resource.title, site.reverse(f"{resource.key}_list")),
            (action.label, ""),
        ),
    )
    template_name = (
        "modern_admin/partials/action_dialog.html"
        if is_htmx(request)
        else "modern_admin/pages/action.html"
    )
    response = render(request, template_name, context)
    if request.method == "POST" and form.errors:
        response.status_code = 422
    return response


def resource_tab_view(
    request: HttpRequest,
    *,
    site: ModernAdminSite,
    resource_key: str,
    object_id: str,
    tab_key: str,
) -> HttpResponse:
    if response := _guard(request):
        return response
    resource = site.get_resource(resource_key)
    obj = get_object_or_404(resource.get_queryset(request), pk=object_id)
    if not resource.permission_policy.can_view(request.user, obj):
        return _permission_denied(request, site)
    tab = next(
        (
            candidate
            for candidate in resource.get_detail_tabs(request, obj)
            if candidate.key == tab_key
        ),
        None,
    )
    if tab is None:
        raise Http404(_("Unknown detail tab"))
    context = {
        "resource": resource,
        "object": obj,
        "tab": tab,
        "modern_admin_site": site,
        "request": request,
    }
    context.update(_detail_tab_context(request, resource, obj, tab))
    return render(request, tab.template_name, context)


def dashboard_view(request: HttpRequest, *, site: ModernAdminSite) -> HttpResponse:
    if response := _guard(request):
        return response
    dashboard = site.get_dashboard()
    if not dashboard.has_permission(request):
        return _first_permitted_destination(request, site)
    widgets = tuple(
        (widget, dict(widget.get_context(request))) for widget in dashboard.get_widgets(request)
    )
    widget_map = {widget.key: {"widget": widget, "context": context} for widget, context in widgets}
    context = _site_context(
        site,
        request,
        dashboard=dashboard,
        widgets=widgets,
        widget_map=widget_map,
        breadcrumbs=((_("Overview"), ""),),
    )
    context = dashboard.get_context_data(request, **context)
    return render(request, dashboard.template_name, context)


def widget_view(request: HttpRequest, *, site: ModernAdminSite, widget_key: str) -> HttpResponse:
    if response := _guard(request):
        return response
    dashboard = site.get_dashboard()
    if not dashboard.has_permission(request):
        return _permission_denied(request, site)
    widget = next((item for item in dashboard.get_widgets(request) if item.key == widget_key), None)
    if widget is None:
        raise Http404(_("Unknown dashboard widget"))
    return render(
        request,
        "modern_admin/partials/widget.html",
        {
            "widget": widget,
            "widget_context": dict(widget.get_context(request)),
            "modern_admin_site": site,
        },
    )


def page_view(
    request: HttpRequest,
    *,
    site: ModernAdminSite,
    page_key: str,
) -> HttpResponse:
    if response := _guard(request):
        return response
    page = next((item for item in site.registry.pages if item.key == page_key), None)
    if page is None:
        raise Http404(_("Unknown custom page"))
    if not page.has_permission(request):
        return _permission_denied(request, site)
    context = _site_context(
        site,
        request,
        breadcrumbs=((_("Overview"), site.reverse("dashboard")), (page.title, "")),
    )
    context = page.get_context_data(request, **context)
    return render(request, page.template_name, context)


def command_palette_view(request: HttpRequest, *, site: ModernAdminSite) -> HttpResponse:
    if response := _guard(request):
        return response
    query = request.GET.get("q", "").strip()
    navigation_results: list[dict[str, str]] = []
    object_results: list[dict[str, str]] = []
    create_results: list[dict[str, str]] = []
    for group in site.get_navigation(request).values():
        for item in group:
            if not query or query.casefold() in item.label.casefold():
                navigation_results.append({"label": item.label, "url": item.url, "icon": item.icon})
    if query:
        for resource in site.registry.resources:
            if not resource.permission_policy.can_view(request.user) or not resource.search_fields:
                continue
            objects = resource.search_queryset(request, resource.get_queryset(request), query)[:4]
            for obj in objects:
                if not resource.permission_policy.can_view(request.user, obj):
                    continue
                object_results.append(
                    {
                        "label": resource.get_object_label(obj),
                        "meta": capfirst(resource.model._meta.verbose_name),
                        "url": site.reverse(f"{resource.key}_detail", args=(obj.pk,)),
                        "icon": resource.icon,
                    }
                )
    else:
        for resource in site.registry.resources:
            if resource.has_form and resource.permission_policy.can_add(request.user):
                create_results.append(
                    {
                        "label": _("New %(model)s") % {"model": resource.verbose_name},
                        "meta": resource.title,
                        "url": site.reverse(f"{resource.key}_create"),
                        "icon": resource.icon,
                    }
                )
    return render(
        request,
        "modern_admin/partials/command_results.html",
        {
            "query": query,
            "navigation_results": navigation_results[:8],
            "object_results": object_results[:8],
            "create_results": create_results[:5],
        },
    )


def relation_filter_choices_view(request, *, site, resource_key, filter_key):
    if response := _guard(request):
        return response
    resource = site.get_resource(resource_key)
    if not resource.has_permission(request) or not resource.permission_policy.can_view(
        request.user
    ):
        return _permission_denied(request, site)
    filter_ = next((f for f in resource.get_filters(request) if f.key == filter_key), None)
    if not isinstance(filter_, RelationFilter) or filter_.choices is not None:
        raise Http404(_("Unknown relation filter"))
    page = Paginator(
        filter_.search(request, resource, request.GET.get("q", "").strip()),
        min(filter_.limit, 100),
    ).get_page(request.GET.get("page", 1))
    return JsonResponse(
        {
            "results": [
                {"value": filter_.option_value(obj, resource), "label": str(obj)}
                for obj in page
                if filter_.can_view_option(request, resource, obj)
            ],
            "page": page.number,
            "pages": page.paginator.num_pages,
            "has_next": page.has_next(),
            "has_previous": page.has_previous(),
        }
    )


def _detail_tab_context(request, resource, obj, tab):
    if not isinstance(tab, RelatedObjectList):
        return dict(tab.context(request, obj)) if tab.context else {}
    site = resource.site
    child = site.get_resource(tab.resource_key)
    if not child.has_permission(request) or not child.permission_policy.can_view(request.user):
        return {"related_denied": True}
    relation = child.model._meta.get_field(tab.relation_field)
    if relation.related_model is not resource.model:
        from modern_admin.exceptions import InvalidResourceConfiguration

        raise InvalidResourceConfiguration("RelatedObjectList relation must point to its parent.")
    queryset = child.get_queryset(request).filter(**{tab.relation_field: obj}).distinct()
    queryset = queryset.order_by(*child.get_ordering(request), "pk")
    page = Paginator(queryset, tab.page_size).get_page(request.GET.get("related_page", 1))
    columns = child.get_list_display(request)
    rows = []
    for item in page:
        if not child.permission_policy.can_view(request.user, item):
            continue
        rows.append(
            {
                "label": child.get_object_label(item),
                "cells": tuple(column.get_cell(item, child, request) for column in columns),
                "url": site.reverse(f"{child.key}_detail", args=(item.pk,)),
                "edit_url": site.reverse(f"{child.key}_edit", args=(item.pk,))
                if child.has_form and child.permission_policy.can_change(request.user, item)
                else "",
                "actions": tuple(
                    ActionLink(
                        action=action,
                        url=site.reverse(f"{child.key}_action", args=(item.pk, action.key)),
                        unavailable_reason=action.get_unavailable_reason(request, item),
                    )
                    for action in child.get_actions(request, "row", item)
                ),
            }
        )
    detail_url = site.reverse(f"{resource.key}_detail", args=(obj.pk,))

    def page_url(number):
        return detail_url + "?" + urlencode({"tab": tab.key, "related_page": number})

    return {
        "related_refresh_url": site.reverse(f"{resource.key}_tab", args=(obj.pk, tab.key))
        + "?"
        + urlencode({"related_page": page.number}),
        "related_label": tab.label,
        "related_rows": rows,
        "related_columns": columns,
        "related_page": page,
        "related_previous_url": page_url(page.previous_page_number())
        if page.has_previous()
        else "",
        "related_next_url": page_url(page.next_page_number()) if page.has_next() else "",
    }
