# Modern Admin architecture

This document is intentionally written before the implementation. It defines the
smallest set of abstractions that lets ordinary Django CRUD and bespoke business
workflows coexist without turning the framework into a second ORM or a hidden SPA.

## Product boundary

Modern Admin is a reusable Django application that owns presentation, routing, and
resource orchestration. Django continues to own models, querysets, forms,
authentication, permissions, CSRF, validation, messages, and transactions. HTMX
replaces fragments; Alpine only owns ephemeral browser state such as whether a
dialog or menu is open.

The central rule is:

```text
resource configuration -> generated Django view
custom workflow         -> ordinary Django view/service/template in the same shell
```

The framework includes resource CRUD, filters, actions, UI components, navigation,
dashboards, and optional audit events. It does not include tenancy, workflow/state
machines, background jobs, billing logic, reporting engines, or domain services.
Those stay in the application and are called by resource hooks or actions.

## Package structure

```text
modern_admin/
  __init__.py                 stable public imports
  apps.py                     Django application and system-check loading
  sites.py                    Site, registration, URL assembly
  registry.py                 typed registry and configuration errors
  resources/
    base.py                   Resource and navigation metadata
    model.py                  ModelResource and its extension hooks
    page.py                   PageResource
    dashboard.py              Dashboard and widget layout
    columns.py                bound list/detail presentation columns
    filters.py                URL-backed queryset filters
    actions.py                typed business-action protocol
    sections.py               detail sections and lazy tabs
    widgets.py                dashboard widget protocol
  views/
    resources.py              thin list/detail/form/action dispatchers
    pages.py                  dashboard, page, command palette
    mixins.py                 auth, resource lookup, HTMX rendering
  forms/
    fields.py                 opt-in richer Django form fields/widgets
  permissions.py              default Django permission policy
  responses.py                HTMX events, redirects, and toast helpers
  audit.py                    optional audit recording service
  models.py                   decoupled AuditEvent record
  navigation.py               immutable navigation tree values
  checks.py                   Django system checks
  templatetags/modern_admin.py presentation helpers only
  templates/modern_admin/     compositional pages, partials, components
  static/modern_admin/        Tailwind source/build, compact Alpine controller
  urls.py                     optional default site include
  tests/                      reusable-app tests

demo/
  config/                     runnable Django project
  commerce/                   realistic CRM/order domain and services
  templates/                  supported project-level overrides
```

The first implementation may combine very small related modules, but no module is
allowed to become an all-purpose framework dumping ground.

## Core abstractions

### `Site`

Owns a registry, a URL namespace, branding, dashboard, custom pages, and navigation
items. A resource instance is bound to exactly one model and one site at
registration. Multiple sites are possible, and `django.contrib.admin` can be
mounted independently.

### `Resource`

Base metadata and permission/navigation hooks shared by model resources and pages.
It is deliberately not a Django view.

### `ModelResource[ModelT]`

The generated CRUD/workflow adapter. Its main hooks are `get_queryset`,
`get_list_display`, `get_filters`, `get_form_class`, `get_actions`,
`get_detail_sections`, and `get_context_data`. It owns configuration, never domain
state. All object lookup starts with `get_queryset(request)`, which makes tenant and
object visibility rules impossible to bypass accidentally in generated endpoints.

### Columns and filters

Columns are small immutable value objects that format an already-fetched object and
declare sort behavior. Filters parse their own URL parameters, validate values, and
apply one queryset transformation. Strings normalize to columns or inferred filters
during registration. Binding/validation happens once, not once per table cell.

### `ResourceAction[ModelT]`

A class representing a user-visible business command. It defines placement,
permission, an optional Django form, and `execute`. Generated views provide GET
dialog rendering and POST validation, but the action calls application services for
business behavior. `ActionResult` carries the user message and UI refresh intent.

### Sections, tabs, and widgets

These are presentation descriptors, not mini view frameworks. Sections group fields
on a detail page. Tabs may render a template and optionally build context through a
resource hook. Widgets render a template and may refresh independently. When a use
case needs more than these contracts, it should be a custom Django view/page.

### `PageResource` and `Dashboard`

A page is a normal shell-aware class-based endpoint with navigation and permission
hooks. A dashboard is a specialized page with an ordered responsive widget list.
They do not imitate models.

## Public API

Stable imports are shallow:

```python
from modern_admin import ModelResource, PageResource, site
from modern_admin.actions import ActionResult, ResourceAction
from modern_admin.columns import BadgeColumn, DateTimeColumn, MoneyColumn
from modern_admin.filters import ChoiceFilter, DateRangeFilter, RelationFilter
from modern_admin.permissions import PermissionPolicy
from modern_admin.sections import DetailSection, DetailTab
from modern_admin.widgets import MetricWidget, RecordsWidget
```

Registration supports both forms:

```python
@site.register(Customer)
class CustomerResource(ModelResource[Customer]):
    pass

site.register(Order, OrderResource)
```

The resource class remains declarative, but every collection has a request-aware
getter so an application can vary it without mutating class attributes.

## Realistic examples

```python
@site.register(Customer)
class CustomerResource(ModelResource[Customer]):
    title = "Customers"
    navigation = Navigation(label="Customers", icon="users", group="Relationships", order=20)
    list_display = [
        TextColumn("name", label="Customer", secondary="email"),
        RelationColumn("organization"),
        BadgeColumn("status", variants={"active": "success", "lead": "neutral"}),
        MoneyColumn("lifetime_value", currency="USD"),
        DateTimeColumn("created_at"),
    ]
    search_fields = ["name", "email", "organization__name"]
    filters = [ChoiceFilter("status"), RelationFilter("organization"), DateRangeFilter("created_at")]
    ordering = ["-created_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            organization__workspace=request.user.profile.workspace,
        ).select_related("organization")
```

```python
class CancelOrder(ResourceAction[Order]):
    key = "cancel"
    label = "Cancel order"
    variant = "danger"
    form_class = CancelOrderForm

    def has_permission(self, request, obj):
        return super().has_permission(request, obj) and obj.can_be_cancelled

    def execute(self, *, request, obj, cleaned_data):
        order_service.cancel(order=obj, reason=cleaned_data["reason"], actor=request.user)
        return ActionResult.success("Order cancelled.", refresh=("#resource-detail", "#activity-tab"))
```

```python
@site.page(path="settings/", label="Workspace settings", icon="settings")
class SettingsPage(PageResource):
    template_name = "commerce/settings.html"

    def has_permission(self, request):
        return request.user.has_perm("commerce.manage_workspace")
```

Project overrides remain ordinary Django:

```python
class CustomerResource(ModelResource[Customer]):
    list_template_name = "commerce/customers/list.html"

    def get_urls(self):
        return [path("merge/", self.admin_view(CustomerMergeView.as_view()), name="merge")]
```

## Standard request lifecycle

1. Django resolves a site-generated URL to a thin view with the registered resource
   key, never an import path supplied by the browser.
2. The site retrieves the already-bound resource and enforces authentication plus
   the resource permission policy.
3. The resource builds its scoped queryset. Detail/edit/action lookup uses this same
   queryset, preserving tenant and object-level visibility.
4. Search, validated filters, ordering allowlists, and pagination are applied in
   that order. Columns are resolved once and rendered against the page objects.
5. The view renders a full shell and page. Templates receive presentation objects,
   not permission or queryset responsibilities.

## HTMX lifecycle

1. Controls use real links/forms with canonical query strings and work without JS.
2. With HTMX, the same URL receives `HX-Request: true`; `HX-Target` selects the
   documented fragment endpoint behavior.
3. The same view builds the same queryset/context, then returns the corresponding
   partial rather than duplicating data logic. List controls use `hx-push-url` so
   history and bookmarks reflect server state.
4. Forms return a form/dialog fragment with status 422 when invalid. Successful
   commands emit structured `HX-Trigger` events (`ma:toast`, `ma:dialog-close`, and
   `ma:refresh`) or a safe `HX-Redirect`.
5. A global error hook replaces failed fragments with a standard error state while
   preserving the current page. History restoration still renders a complete page
   when the request is not an HTMX fragment request.

The server remains authoritative. There is no client-side entity store, router, or
duplicated validation model.

## Permissions

`PermissionPolicy` maps view/add/change/delete to Django's model permissions and
provides action hooks. Resources may replace it or override `get_permission_policy`.
Collection endpoints check resource permission; object endpoints additionally check
object permission after lookup from the scoped queryset. Action visibility and
execution call the same action permission method independently. Hiding a button is
therefore presentation, not enforcement.

## Business actions

Actions are registered class objects on a resource and bound/validated at startup.
GET renders a confirmation or a Django form in the shared dialog surface. POST
re-resolves the object through the scoped queryset, rechecks permission, validates
the form, and calls `execute` inside `transaction.atomic()` where the action opts in.
The action invokes a service; it should not encode domain transitions itself. Normal
requests redirect with Django messages. HTMX requests use response events to close
the dialog, show a toast, and refresh named fragments.

## Framework versus application responsibility

The framework owns consistent list/detail/form/action mechanics, resource routing,
URL-backed state, navigation, shell, widgets, component styles, event protocols,
default model permissions, and generic audit presentation.

The application owns tenant resolution, domain services, state transition rules,
notifications to external systems, background jobs, exports with business meaning,
report definitions, object-specific audit metadata, and any screen whose interaction
model is more naturally expressed as a custom view than CRUD configuration.

## Architecture critique and simplification decisions

### Abstractions deliberately removed

An initial `ResourceList`, `ResourceDetail`, `ResourceForm`, separate registry
interfaces, component Python classes, repositories, and an event bus would mostly
wrap Django concepts. They are omitted. Context dataclasses are used only where they
prevent template ambiguity. Views, QuerySets, Forms, and templates remain visible.

Saved views are stored as canonical query strings behind a small interface rather
than a query-language AST. Detail sections and widgets have narrow render contracts;
they are not recursive layout engines. The component layer is template includes and
tags, not a parallel React-like component runtime.

### Coupling risks

Columns can become coupled to ORM traversal and HTML. Binding limits traversal to
declared paths; `TemplateColumn` is the escape hatch. Actions can become service
objects by accident, so their contract and documentation explicitly restrict them to
UI orchestration. Site URL generation knows resource capabilities, but resources do
not import views, preventing the most likely circular dependency.

### Django convention risks

Class attributes and registration resemble Django admin, but the implementation must
not depend on admin internals. Returning 422 for HTMX validation is useful but Django
forms conventionally return 200; the frontend explicitly accepts both. Custom pages
remain class-based Django endpoints rather than being forced through model-resource
hooks. Django messages are preserved for full navigation.

### Performance risks

Sorting/search across relations can add joins and `distinct()`, exact counts can be
expensive, relation filter choices can grow unbounded, and cells that call arbitrary
properties can hide queries. The framework never guesses `select_related`, exposes
`get_queryset`, only adds `distinct` when relational search requires it, supports
configurable counts, and documents that custom columns must not query. Autocomplete
is used instead of rendering large relation choice sets.

### Typing challenges

Django model field descriptors and runtime registration cannot be fully statically
proved. Generics preserve model type inside resource/action hooks, while field-path
strings receive startup validation and good runtime errors. Pretending string paths
are statically safe would add complexity without safety.

### HTMX pitfalls

Ambiguous target-dependent responses, stale URLs, out-of-order searches, and broken
history are common. The framework uses named fragment request parameters, canonical
GET forms, `hx-sync` for search, and `hx-push-url`. OOB swaps are reserved for global
surfaces (toasts/dialog host), not routine page composition. Responses never infer
authorization from `HX-Request`.

### Where configuration could become harder than Django

Deep custom layouts, multi-object forms, wizards, imports, and highly transactional
workflows should not be expressed as dozens of descriptors. The escape hatch is
explicit and early: subclass a normal Django view, use the site shell/context helper,
and link it through navigation or resource URLs. The framework earns its keep only
for repeated application chrome and conventional resource interactions.

## Delivery slices

1. Shell, site/registry, model resource, columns, search, filters, ordering, and
   pagination.
2. Detail sections, model forms, actions/dialogs/toasts, and permission enforcement.
3. Dashboard widgets, custom pages, lazy tabs, and command palette.
4. Audit timeline, bulk actions, saved-view contract, configuration checks, and
   performance refinements.

Each slice must have tests and a usable demo state before the next begins.
