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

## Permissions and data boundaries

The default site gate requires an active staff user. Resource views then enforce
Django permissions; `is_staff` alone does not grant access to every model.
Assign permissions through your project's groups and roles.

Override `ModernAdminSite.has_permission(request)` for another access model, retaining
an explicit active-user check. A custom `permission_policy_class` can implement
resource-specific rules. The default policy accepts model-level permissions; it is
not a tenant or row-level authorization engine.

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

### Current limitations

| Area | Boundary |
| --- | --- |
| Content Security Policy | The current Alpine runtime evaluates expressions, and templates include inline theme initialization. Strict CSP without runtime/inline allowances requires frontend changes. Do not weaken an existing policy without review. |
| Database concurrency | The automated local suite uses SQLite; it does not establish PostgreSQL row-lock correctness or multi-database transaction guarantees. Test against your deployment database. |
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
leaving the worklist. Never deploy demo settings or credentials.

## Contributing

Focused contributions are welcome: reproducible bugs, accessibility improvements,
integration tests, documentation fixes, and well-scoped extension points.

For a bug report, include Python/Django versions, the database backend, a minimal
resource definition, reproduction steps, and expected versus actual behavior.
Redact customer data, credentials, and tokens. Discuss substantial API changes before
implementing them; preserve Django conventions and keep domain logic out of the framework.

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
