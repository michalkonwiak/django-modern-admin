# Django Modern Admin

### Build a backoffice that feels like a product.

A Django-native framework for internal applications. Turn your models into a
focused workspace with fast tables, contextual actions, record previews, and
business workflows - without building a separate frontend.

**Python 3.13+ · Django 5.2 / 6.0 · Django Templates · HTMX · Alpine.js · Tailwind CSS**

[Get started](#get-started) · [Explore the demo](#explore-the-demo) ·
[Workflows](WORKFLOWS.md) · [Architecture](ARCHITECTURE.md) ·
[Deployment](#deployment) · [Contributing](#contributing)

```python
from modern_admin import ModelResource, site
from modern_admin.columns import BadgeColumn, TextColumn
from modern_admin.filters import ChoiceFilter

from crm.models import Customer


@site.register(Customer)
class CustomerResource(ModelResource[Customer]):
    list_display = (
        TextColumn("name", secondary="email"),
        BadgeColumn("status", variants={"active": "success", "pending": "warning"}),
        "created_at",
    )
    search_fields = ("name", "email")
    filters = (ChoiceFilter("status"),)
    form_fields = ("name", "email", "status")
```

Familiar configuration. A dedicated application experience. Your Django code remains
in control.

## Why Modern Admin?

Internal tools eventually grow beyond editing database rows. Operators need to
review a queue, understand a record, make a decision, and return to their work
without losing context.

Modern Admin is built around that workflow:

- **Start with a resource.** Declare columns, search, filters, forms, and permissions
  around an existing Django model.
- **Keep work in context.** Use HTMX-powered lists, saved views, and record preview
  drawers without navigating away from the current worklist.
- **Model business operations explicitly.** Actions provide forms, authorization,
  validation feedback, and notifications while your services own the business logic.
- **Go beyond CRUD when needed.** Add custom pages, dashboards, detail sections,
  and lazy tabs using ordinary Django views and templates.
- **Ship one application.** Bundled frontend assets, server-side validation, and
  Django sessions—no separate API or JavaScript application required.

This is **not a Django Admin theme**. It does not wrap `ModelAdmin`, copy its
configuration automatically, or depend on `django.contrib.admin`. Both applications
can coexist and operate on the same models.

## What is included

| Area | Capabilities |
| --- | --- |
| Workspace | Compact navigation, breadcrumbs, command palette, light and dark themes |
| Record lists | Typed columns, search, filters, sorting, pagination, selection, saved views |
| Record workspace | Detail sections, lazy tabs, preview drawers, activity timelines |
| Forms | Django ModelForms, explicit editable fields, inline server validation, dialogs |
| Workflows | Resource actions, bulk actions, guarded transitions, scoped work queues |
| Extension points | Custom pages, dashboard widgets, querysets, policies, templates, and URLs |
| Accounts | Opt-in user and group administration with a grouped, searchable permission picker |
| Integration | Namespaced authentication routes, Django permissions, migrations, bundled assets |

### Project status

**Early development · 0.1.0.** The package is installable and has backend, browser,
and isolated-distribution integration tests. The 0.x API may change; pin the version
and test upgrades before deploying.

This is not a claim of universal production readiness. See [deployment](#deployment)
for the current security, database, and compatibility boundaries. A CI matrix is
configured for Django 5.2 and 6.0; verify its results for the revision you adopt.

## Get started

### 1. Install the package

The instructions below install from a local checkout. They do not assume a
published PyPI release.

Build a distribution from the library repository:

```bash
uv build
```

Then install it into your Django project's environment:

```bash
python -m pip install /path/to/framework/dist/django_modern_admin-0.1.0-py3-none-any.whl
```

For local development against the library source:

```bash
python -m pip install -e /path/to/framework
```

Python 3.13 or later is required. Supported dependency bounds are
`Django>=5.2,<6.1`. Compiled CSS, HTMX, and Alpine are included in the wheel;
consuming projects do not need Node or a CDN.

### 2. Configure Django

Merge the following requirements into your existing settings. Keep your project's
applications, middleware, and context processors.

```python
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "modern_admin",
    "crm",  # Your application
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ],
    },
}]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
```

Custom user models are referenced through `AUTH_USER_MODEL`. Configure yours before
the project's first migration and preserve the Django authentication interface,
including `is_authenticated`, `is_active`, `is_staff`, and `has_perm()`.

### 3. Register your resources

Create `config/backoffice.py`, adapting `config` to your project's package name.
This example assumes `crm.models.Customer` already has `name`, `email`, `status`
with Django choices, and `created_at` fields.

```python
from crm.models import Customer
from modern_admin import ModelResource, ModernAdminSite
from modern_admin.columns import BadgeColumn, DateColumn, TextColumn
from modern_admin.filters import ChoiceFilter

backoffice = ModernAdminSite(name="backoffice")
backoffice.site_title = "Acme"
backoffice.site_subtitle = "Workspace"


@backoffice.register(Customer)
class CustomerResource(ModelResource[Customer]):
    list_display = (
        TextColumn("name", secondary="email"),
        BadgeColumn("status", variants={"active": "success", "blocked": "danger"}),
        DateColumn("created_at"),
    )
    search_fields = ("name", "email")
    filters = (ChoiceFilter("status"),)
    ordering = ("-created_at",)
    form_fields = ("name", "email", "status")
```

**Generated create/edit forms are opt-in.** Set `form_fields` or supply your own
`form_class`. Listing a field does not make it editable. Prefer an explicit field
allowlist over `"__all__"` so future model changes do not silently expand access.
Business actions have their own authorization and may still be available without
generated forms.

Import resource configuration from your URLconf—not `settings.py` or the project's
root `__init__.py`—so models are registered after Django initializes its apps.

### 4. Mount the workspace

```python
# config/urls.py
from django.urls import path
from config.backoffice import backoffice

urlpatterns = [
    path("app/", backoffice.urls),
]
```

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py check
python manage.py runserver
```

Open `/app/` and sign in. The package migrations create audit and saved-view tables;
they do not change your business models' schema.

| Route | Purpose |
| --- | --- |
| `/app/` | Dashboard |
| `/app/login/` | Sign in |
| `/app/logout/` | Sign out; POST with CSRF protection |
| `/app/customer/` | Customer list |
| `/app/customer/new/` | Create a customer |
| `/app/customer/123/` | Customer details |
| `/app/customer/123/edit/` | Edit a customer |

Routes are namespaced: `reverse("backoffice:customer_list")`. No global `login` or
`logout` URL names are required, and the project's `LOGIN_URL` can remain unchanged.

To keep Django Admin alongside the workspace, retain its existing `/admin/` route.
To use Modern Admin at `/admin/`, mount `backoffice.urls` there and move the original
admin to a separate prefix. Existing `ModelAdmin` classes are not automatically ported.

## Built for workflows

Simple screens should take a small amount of configuration. Complex operations
should remain understandable Django code.

Use `ResourceAction` for a business operation with a form and result notification.
Use `TransitionAction` when execution must check the record's current state.
Use `WorkQueue` to present a request-scoped subset of records with worklist counters.

The [workflow guide](WORKFLOWS.md) covers complete examples, authorization,
transaction boundaries, and the order-review demo. Business rules belong in your
service layer; the resource coordinates presentation and access.

Bulk actions validate permissions for each selected record and accept at most 1,000
submitted identifiers. Delegate long-running exports and integrations to your
application's task queue. Avoid holding row locks during external network calls.

### Custom pages

```python
from modern_admin import PageResource


@backoffice.page(path="reports/", label="Reports", icon="chart-bar")
class ReportsPage(PageResource):
    template_name = "reports/index.html"
```

Your template can extend `modern_admin/layouts/app.html`. Override its permission
hook and context as needed. Custom resource URLs pass through the site's access
gate, but their views must enforce operation-specific and object-specific permissions.

### Your design, your templates

Override templates through Django's normal template loader, or load project styles:

```python
backoffice.extra_css = ("css/backoffice.css",)
```

The UI uses CSS tokens and ordinary Django template composition. You can customize
the application without introducing a component runtime or maintaining a fork.
See [architecture and extension points](ARCHITECTURE.md).

## Deleting records

Every model resource includes a **Delete** entry in its row menu, detail page, and
record preview. It uses the existing confirmation dialog and danger-button styles.
The confirmation lists counts by model, including cascaded records. Deletion only
runs on a CSRF-protected POST with a signed confirmation; a changed deletion graph
or an expired confirmation requires another review. `PROTECT` and `RESTRICT`
relationships display a blocking explanation.

The operator must have both view and delete access to the record. Cascaded models
registered on the site also enforce their resource policies and scoped querysets;
unregistered models require Django delete permission. Implicit many-to-many links
do not require separate permissions. Set `delete_enabled = False` on a resource to
disable deletion, or customize `PermissionPolicy.can_delete(user, obj)` for business
rules. The built-in account policy prevents users from deleting their own account.

The `{resource_key}_delete` URL accepts the object's primary key, for example
`reverse("modern_admin:customer_delete", args=(customer.pk,))`. The full-page fallback
works without JavaScript and can be customized with `delete_template_name`.
Successful deletion returns to the resource list, preserving worklist filters when
opened there, and shows a success notification. A `deleted` audit event retains the
original identity and label; deletion and its audit write share one transaction and
write database. Override `delete_object(request, obj)` to call your domain service
inside that transaction; the default calls `obj.delete()` and honors model overrides.
The confirmation describes Django's hard-delete graph, so custom deletion hooks must
not delete additional objects outside that reviewed graph.

## Permissions and data boundaries

The default site gate requires an active staff user. Resource views then enforce
Django permissions; `is_staff` alone does not grant access to every model.
Assign permissions through your project's groups and roles.

Override `ModernAdminSite.has_permission(request)` for another access model, retaining
an explicit active-user check. A custom `permission_policy_class` can implement
resource-specific rules. The default policy accepts model-level permissions; it is
not a tenant or row-level authorization engine.

Navigation follows authorization: a resource appears in the sidebar only when the
operator may view it, and pages and dashboards are gated by `permission_required`.
Operators who cannot open the dashboard land on their first permitted destination
instead of an error page.

```python
@backoffice.page(path="settings/", label="Settings", icon="settings", group="System")
class SettingsPage(PageResource):
    permission_required = "crm.view_workspace_settings"
    template_name = "settings/index.html"
```

Permissions for pages that have no records of their own live on any model you choose.
A small unmanaged model keeps them out of an unrelated table:

```python
class WorkspaceAccess(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = (("view_workspace_settings", "Can view workspace settings"),)
```

### Managing accounts

Account administration is opt-in. Register it on your site to manage Django users,
group membership, and individual permissions inside the workspace:

```python
from modern_admin import site
from modern_admin.accounts import register_accounts

register_accounts(site)
```

This adds `Users` and `Groups` resources with a searchable, grouped permission
picker, and a `Set password` action that uses Django's `SetPasswordForm`. Access
follows Django's own model permissions (`auth.view_user`, `auth.change_user`, and
so on), with one added guard: only superusers may edit superuser accounts or grant
superuser status. The bundled resources expect an `AbstractUser`-shaped model;
for a different user model, subclass `UserResource` and register it yourself.

`AccessChecklist` (`modern_admin.forms`) is the widget behind the picker and works
with any `ModelMultipleChoiceField` whose choices are long enough to need filtering.

Scope tenant-owned resources explicitly:

```python
def get_queryset(self, request):
    return (
        super().get_queryset(request)
        .filter(organization=request.organization)
        .select_related("organization")
    )
```

Your project must supply `request.organization`. Also scope relational form fields,
relation filters, widgets, custom pages, and services. Assign ownership server-side
in `save_form`; do not trust a tenant identifier submitted by the browser.

Audit events record an actor, operation, object identity, and timestamp. Action form
contents are not automatically copied into metadata. Use
`modern_admin.audit.record_event` for explicitly selected, non-sensitive metadata.
This is an application activity log, not a tamper-proof compliance ledger or a log
of every ORM write.

## Deployment

Treat the workspace as part of your Django application's security boundary.

- Pin the distribution and test migrations, roles, and workflows in staging.
- Configure `DEBUG=False`, `ALLOWED_HOSTS`, secret management, HTTPS, secure cookies,
  and trusted proxy settings. Run `python manage.py check --deploy`.
- Run `python manage.py collectstatic --noinput` and serve the collected assets
  through your deployment's static-file infrastructure. Do not use `runserver`.
- Use a standard WSGI or ASGI deployment. Resource logic is synchronous; HTMX does
  not require async Python views or WebSockets.
- Keep authenticated responses out of shared caches. Protected site responses use
  `no-store` and vary by session/HTMX headers. Expired HTMX sessions redirect the page.
- Provide login throttling, MFA or SSO, monitoring, backups, audit retention, and
  authorized upload handling in your project.

### PostgreSQL

Install the PostgreSQL driver alongside the library:

```bash
pip install 'django-modern-admin[postgres]'
```

Configure your application's standard Django `DATABASES` setting (PostgreSQL 14+
for the supported Django versions). Credentials belong in your environment or
secret manager:

```python
import os

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["PGDATABASE"],
        "USER": os.environ["PGUSER"],
        "PASSWORD": os.environ["PGPASSWORD"],
        "HOST": os.environ["PGHOST"],
        "PORT": os.environ.get("PGPORT", "5432"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 10},
    }
}
```

Run `python manage.py migrate` before serving requests. Configure TLS through
`OPTIONS` (`sslmode` and `sslrootcert`) according to your database provider.
See [Django's PostgreSQL documentation](https://docs.djangoproject.com/en/6.0/ref/databases/#postgresql-notes)
for connection pooling, persistent connections, and isolation settings.

Atomic actions lock selected base rows in primary-key order, then reload records
and check permissions and business preconditions while holding those locks.
Scoped querysets may include nullable joins, `distinct()`, and aggregations.
Form saves and their audit entries share a transaction on the write database;
custom hooks and audit routers must write to that same database for rollback to
cover every write. Actions with `atomic=False` have no framework locking or
rollback guarantee. Use `transaction.on_commit()` for external side effects such
as queued jobs; database rollback cannot undo an HTTP call or sent email.
Ordinary edit forms do not provide optimistic conflict detection for stale edits.

The repository's demo and test settings enable PostgreSQL with
`MODERN_ADMIN_POSTGRES=1` and the `PG*` variables above. To run the suite against
a dedicated local PostgreSQL instance:

```bash
uv sync --extra test --extra postgres
MODERN_ADMIN_POSTGRES=1 PGDATABASE=modern_admin PGUSER=postgres \
  PGHOST=127.0.0.1 PGPORT=5432 uv run --extra test --extra postgres pytest
```

Supply `PGPASSWORD` separately. The test role needs permission to create test
databases. CI runs the non-browser suite on PostgreSQL 14 and 18 with Django 5.2
and 6.0, including simultaneous action requests on independent connections,
rollback, JSON audit metadata, and queries with joins and aggregation.

### Current limitations

| Area | Boundary |
| --- | --- |
| Content Security Policy | The bundled Alpine CSP build requires no `unsafe-eval`. Enable nonce middleware/context processing as described below; inline CSS attributes remain explicitly allowed. |
| Database concurrency | PostgreSQL action locking is covered by integration tests. Transactions spanning multiple databases and conflict detection for ordinary stale edit forms are not provided. Test custom services and routers against your deployment database. |
| Authentication | Built-in Django login does not add MFA or rate limiting. Existing SSO may authenticate the same Django session. |
| Localization | UI copy is primarily English; full localization is not complete. |
| Migration from Django Admin | Resource definitions, operational permissions, and custom actions must be ported explicitly. |

## Explore the demo

The repository includes a commerce demo with customers, orders, invoices, payments,
products, and operational workflows. The demo is not required by the installed package.

From the repository root:

```bash
uv sync --extra test
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000/app/` and sign in with `demo` / `demo`.
Try **Orders → Ready to ship → record preview** to explore a workflow without
leaving the worklist. The seed also creates the `ops`, `billing`, `support`, and
`workspace-admin` operators (password `demo`), each in a group with different
permissions—sign in as one to see navigation change with authorization, and edit
their access under **System → Users**. Never deploy demo settings or credentials.

## Contributing

Focused contributions are welcome: reproducible bugs, accessibility improvements,
integration tests, documentation fixes, and well-scoped extension points.

For a bug report, include Python/Django versions, the database backend, a minimal
resource definition, reproduction steps, and expected versus actual behavior.
Redact customer data, credentials, and tokens. Discuss substantial API changes before
implementing them; preserve Django conventions and keep domain logic out of the framework.

Install GNU gettext (`msgfmt` on PATH) for translation catalogue checks:
`sudo apt-get install gettext` on Debian/Ubuntu, or `brew install gettext` on macOS.
The tests compare compiled translations with the source content, independent of
file timestamps after a Git checkout.

Run the relevant checks before submitting a change:

```bash
uv sync --extra test
uv run pytest -m 'not browser'
uv run ruff check modern_admin tests
uv run python -m playwright install chromium
uv run pytest tests/browser -m browser
uv build
```

When modifying styles, rebuild the bundled CSS:

```bash
npm install
npm run css:build
```

Include tests and update documentation when behavior or public APIs change. UI changes
should be reviewed in both themes, at desktop and mobile sizes, with keyboard access.

### Security reports

Please report suspected vulnerabilities privately to
[michalkonwiak1@gmail.com](mailto:michalkonwiak1@gmail.com), rather than opening a
public issue with exploit details. Include affected versions, reproduction steps,
and impact; never send live credentials or production customer data.

## Author and license

Created and maintained by **Michal Konwiak**.

[michalkonwiak1@gmail.com](mailto:michalkonwiak1@gmail.com)

Released under the [MIT License](LICENSE). Bundled third-party assets remain subject
to their respective licenses.

### Relation filters and related record lists

`RelationFilter("organization", search_fields=("name", "domain"), limit=50)`
searches records on the server. `limit` controls the page size (maximum 100),
not the total number of available choices. Previous/Next controls reach every
page; the selected value remains visible even when it is outside the first page.
Without `search_fields`, the registered resource’s search fields (or local text
fields if none are configured) and an exact primary key are searched.
Explicit `choices=` retain the ordinary choice picker. Registered related models
use their resource's permissions and `get_queryset(request)`; unregistered models
are restricted to relations present in the source resource's scoped queryset.
Override `RelationFilter.get_queryset()` for additional tenant or business scoping.

Use `RelatedObjectList` as a detail tab when a relation needs its own table instead
of an inline formset:

```python
from modern_admin import RelatedObjectList

class CustomerResource(ModelResource):
    detail_tabs = (
        RelatedObjectList(
            "orders", "Orders", resource_key="order",
            relation_field="customer", page_size=25,
        ),
    )
```

The child resource must be registered on the same site. Its queryset, ordering,
columns, object view/change permissions, form and `row` actions are reused.
`relation_field` is the child's relation to the parent. The list is paginated,
has an empty state, opens editing through the child form and runs actions in a
dialog. After an action, the list refreshes without losing the active tab. These
endpoints retain their existing validation, CSRF and audit behavior. Configure request/tenant visibility in the child resource's
`get_queryset(request)`, just as for its main list. The demo's customer Orders tab
uses this component.

### Content Security Policy

The bundled Alpine runtime is `@alpinejs/csp@3.17.1`; complex handlers live in
`app.js`. HTMX has `allowEval=false` and receives the document nonce through its
`inlineScriptNonce` and `inlineStyleNonce` configuration. The early theme script
also carries that nonce. HTMX fragments use the already loaded document's config;
do not replace it with the nonce of a later fragment response.

Enable `modern_admin.csp.ContentSecurityPolicyMiddleware` in `MIDDLEWARE` and
`modern_admin.csp.csp` in the Django template context processors. On Django 6 these
are aliases of the built-in middleware/context processor; on Django 5.2 they
provide the same nonce and enforcing-header integration for this policy:

```python
SECURE_CSP = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "<CSP_NONCE_SENTINEL>"],
    "style-src": ["'self'", "<CSP_NONCE_SENTINEL>"],
    "style-src-attr": ["'unsafe-inline'"],
    "img-src": ["'self'", "data:"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "frame-ancestors": ["'self'"],
}
```

The demo enforces this policy. Scripts need neither `unsafe-eval` nor
`unsafe-inline`. Style attributes remain allowed for layout variables and Alpine
positioning/transitions; this is not a policy that forbids all inline CSS.
The Django 5.2 adapter supports `SECURE_CSP`, preserves an existing CSP header,
and does not implement Django 6's report-only settings or per-view decorators.
Do not cache full HTML independently of its nonce-bearing CSP header.
See [Django CSP](https://docs.djangoproject.com/en/6.0/ref/csp/) and
[Alpine CSP expressions](https://alpinejs.dev/advanced/csp) for extension guidance.


### Column query diagnostics

Framework cell rendering (lists, related tables, and detail columns) emits
`modern_admin.rendering.ColumnQueryWarning` for database queries when `DEBUG=True`,
including queries inside custom `get_cell()` implementations and `TemplateColumn`
templates. Load relations and computed data in `get_queryset()` with
`select_related()`, `prefetch_related()`, or annotations.

Set `MODERN_ADMIN_COLUMN_QUERIES = "error"` in test settings to raise
`ColumnQueryError` before a query executes. `"warn"` enables diagnostics regardless
of DEBUG; `"off"` disables them (the default outside DEBUG). All configured database
aliases are covered. The guard covers cell evaluation, not arbitrary page context,
actions, or code that calls `get_cell()` directly; custom renderers can use
`modern_admin.rendering.render_cell(column, obj, resource, request)`.

### GET forms on custom pages and widgets

`PageResource` and `Dashboard` support named fragments:

```python
class ReportPage(PageResource):
    path = "report"
    template_name = "reports/page.html"
    fragments = {"results": "reports/results.html"}
```

Include `reports/results.html` in the full page. That partial must contain its
replacement root, for example `<section id="report-results">...</section>`.
Use the shared tag in a page or `TemplateWidget` template:

```html+django
{% load modern_admin %}
<form {% fragment_form "#report-results" "results" %}>
  <input type="search" name="q" value="{{ request.GET.q }}">
  <button type="submit">Search</button>
</form>
{% include "reports/results.html" %}
```

The tag uses the current request path, a real GET action, debounced input events,
`hx-sync="this:replace"`, and `hx-push-url`. Put all filters inside the form so each
request represents the current state. An optional `url=` argument points the form
at another page; use the owning page/dashboard URL for widgets also rendered via
a refresh endpoint. Declare the fragment on that destination page/dashboard.

The view selects only registered fragment names, never infers them from
`HX-Target`, returns 404 for unknown HTMX fragments, and pushes a URL without the
transport-only `fragment` parameter. Normal navigation and history restoration
render the full page. Custom Django endpoints can reuse
`modern_admin.responses.render_fragment(request, template_name, context, fragments=...)`.
Handwritten HTMX forms still need to follow the same contract; arbitrary HTML is
not automatically rewritten.

### First-visit workspace tour

The shared app shell offers a four-step tour on an account's first authenticated
visit to each admin site. It introduces navigation, workspace search, language,
and theme controls using the existing design tokens. The spotlight follows visible
controls and adapts to mobile layouts; Escape, Skip, and the close button dismiss
it. The Replay tour button in Settings opens it again.

Apply migrations when upgrading:

```bash
python manage.py migrate
```

`ProductTourState` stores completion or dismissal per `AUTH_USER_MODEL` account and
site name, so the decision survives logout, cleared browser storage, and different
devices. Existing accounts without a decision see it on their next visit. Closing
the browser before a decision leaves the tour eligible. Replaying never resets the
original decision. Projects may opt out with `site.product_tour_enabled = False`.

Status is loaded from an authenticated, uncached endpoint without adding a query to
list/fragment rendering. Updates require POST and CSRF, with a database uniqueness
constraint for retries. If status loading fails, the workspace remains usable; if
saving fails, a message explains that the tour may reappear. With JavaScript
disabled, the tour and its replay control stay hidden.
