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
from django.db import connections, models, transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, QueryDict
from django.shortcuts import get_object_or_404, render
from django.utils.http import url_has_allowed_host_and_scheme

from modern_admin.audit import events_for, record_event
from modern_admin.columns import Cell, Column
from modern_admin.models import SavedView
from modern_admin.resources import ModelResource
from modern_admin.responses import Toast, htmx_events, is_htmx, notify
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
    message: str = "You do not have access to this page.",
) -> HttpResponse:
    template = (
        "modern_admin/partials/error_state.html"
        if is_htmx(request)
        else "modern_admin/pages/error.html"
    )
    context = site.each_context(request) | {
        "status": 403,
        "title": "Access restricted",
        "message": message,
        "breadcrumbs": (("Access restricted", ""),),
    }
    return render(request, template, context, status=403)


def _site_context(site: ModernAdminSite, request: HttpRequest, **context: Any) -> dict[str, Any]:
    return site.each_context(request) | context


def _query_url(request: HttpRequest, **changes: str | int | None) -> str:
    params = request.GET.copy()
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
        raise Http404("Unknown or unavailable work queue")
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
    saved_params = request.GET.copy()
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
        breadcrumbs=(("Overview", site.reverse("dashboard")), (resource.title, "")),
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
    name = forms.CharField(max_length=100, label="View name")
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
        message = f"Saved view “{form.cleaned_data['name']}”."
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
            ("Overview", site.reverse("dashboard")),
            (resource.title, site.reverse(f"{resource.key}_list")),
            ("Save view", ""),
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
    if initial_tab and initial_tab.context:
        initial_tab_context.update(initial_tab.context(request, obj))
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
        audit_events=events_for(obj)[:20],
        breadcrumbs=(
            ("Overview", site.reverse("dashboard")),
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


def _style_form(form: Any) -> None:
    for field in form.fields.values():
        widget = field.widget
        current = widget.attrs.get("class", "")
        if widget.is_hidden:
            continue
        if widget.__class__.__name__ in {"CheckboxInput", "RadioSelect"}:
            classes = "ma-checkbox"
        elif widget.__class__.__name__ == "Textarea":
            classes = "ma-input ma-textarea"
        else:
            classes = "ma-input"
        widget.attrs["class"] = f"{current} {classes}".strip()
        if not isinstance(widget, forms.Select):
            widget.attrs.setdefault("placeholder", field.label)


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
        raise Http404("Forms are not configured for this resource.")
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
        saved = resource.save_form(request, form, change=obj is not None)
        action_name = "updated" if obj else "created"
        record_event(request=request, action=action_name, obj=saved)
        message = f"{resource.model._meta.verbose_name.title()} {action_name} successfully."
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
        page_title=f"Edit {resource.get_object_label(obj)}"
        if obj
        else f"New {resource.model._meta.verbose_name}",
        submit_label="Save changes" if obj else f"Create {resource.model._meta.verbose_name}",
        cancel_url=(
            site.reverse(f"{resource.key}_detail", args=(obj.pk,))
            if obj
            else site.reverse(f"{resource.key}_list")
        ),
        breadcrumbs=(
            ("Overview", site.reverse("dashboard")),
            (resource.title, site.reverse(f"{resource.key}_list")),
            ("Edit" if obj else "New", ""),
        ),
    )
    if dialog:
        response = render(request, "modern_admin/partials/form_dialog.html", context)
    else:
        response = render(request, resource.form_template_name, context)
    if request.method == "POST" and form.errors and is_htmx(request):
        response.status_code = 422
    return response


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
        raise Http404("Unknown resource action")
    placements = {"row", "detail"} if object_id is not None else {"bulk", "resource"}
    if not placements.intersection(action.placements):
        raise Http404("Action is not available at this endpoint")
    obj = get_object_or_404(resource.get_queryset(request), pk=object_id) if object_id else None
    if not action.has_permission(request, obj):
        return _permission_denied(request, site, "You cannot run this action.")
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
                        connection = connections[execution_queryset.db]
                        lock_options = (
                            {"of": ("self",)}
                            if connection.features.has_select_for_update_of
                            else {}
                        )
                        execution_queryset = execution_queryset.select_for_update(**lock_options)
                    obj = get_object_or_404(execution_queryset, pk=object_id)
                    if not action.has_permission(request, obj):
                        return _permission_denied(request, site, "You cannot run this action.")
                    action.validate_execution(request, obj)
                    result = action.execute(
                        request=request, obj=obj, cleaned_data=form.cleaned_data
                    )
                    record_event(request=request, action=action.key, obj=obj)
                else:
                    selected = request.POST.getlist("selected")
                    if not selected or len(selected) > 1000:
                        raise ValidationError("Select between 1 and 1,000 records.")
                    queryset = resource.get_queryset(request).filter(pk__in=selected)
                    objects = list(queryset)
                    if len(objects) != len(set(selected)) or any(
                        not action.has_permission(request, item) for item in objects
                    ):
                        return _permission_denied(request, site, "Selection is not permitted.")
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
                    raise ValidationError("The action returned an unsafe redirect URL.")
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
                    refresh=tuple(dict.fromkeys((*result.refresh, "#record-preview")))
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
            ("Overview", site.reverse("dashboard")),
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
        raise Http404("Unknown detail tab")
    context = {
        "resource": resource,
        "object": obj,
        "tab": tab,
        "modern_admin_site": site,
        "request": request,
    }
    if tab.context:
        context.update(tab.context(request, obj))
    return render(request, tab.template_name, context)


def dashboard_view(request: HttpRequest, *, site: ModernAdminSite) -> HttpResponse:
    if response := _guard(request):
        return response
    dashboard = site.dashboard_class(site)
    if not dashboard.has_permission(request):
        return _permission_denied(request, site)
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
        breadcrumbs=(("Overview", ""),),
    )
    context = dashboard.get_context_data(request, **context)
    return render(request, dashboard.template_name, context)


def widget_view(request: HttpRequest, *, site: ModernAdminSite, widget_key: str) -> HttpResponse:
    if response := _guard(request):
        return response
    dashboard = site.dashboard_class(site)
    if not dashboard.has_permission(request):
        return _permission_denied(request, site)
    widget = next((item for item in dashboard.get_widgets(request) if item.key == widget_key), None)
    if widget is None:
        raise Http404("Unknown dashboard widget")
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
        raise Http404("Unknown custom page")
    if not page.has_permission(request):
        return _permission_denied(request, site)
    context = _site_context(
        site,
        request,
        breadcrumbs=(("Overview", site.reverse("dashboard")), (page.title, "")),
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
                        "meta": resource.model._meta.verbose_name.title(),
                        "url": site.reverse(f"{resource.key}_detail", args=(obj.pk,)),
                        "icon": resource.icon,
                    }
                )
    else:
        for resource in site.registry.resources:
            if resource.has_form and resource.permission_policy.can_add(request.user):
                create_results.append(
                    {
                        "label": f"New {resource.verbose_name}",
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
