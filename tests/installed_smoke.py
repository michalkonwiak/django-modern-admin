"""Run against an extracted wheel, outside this repository (no demo dependency)."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings

with TemporaryDirectory(prefix="modern-admin-installed-") as directory:
    settings.configure(
        SECRET_KEY="isolated-test-only",
        DEBUG=False,
        ALLOWED_HOSTS=["testserver"],
        ROOT_URLCONF=__name__,
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "modern_admin",
        ],
        MIDDLEWARE=[
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(Path(directory) / "db.sqlite3"),
            }
        },
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ]
                },
            }
        ],
        STATIC_URL="/static/",
        STATIC_ROOT=str(Path(directory) / "static"),
        STORAGES={
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
            }
        },
    )
    import django

    django.setup()
    from django.contrib.auth.models import Group, User
    from django.core.management import call_command
    from django.test import Client
    from django.urls import path

    from modern_admin.accounts import register_accounts
    from modern_admin.sites import ModernAdminSite

    site = ModernAdminSite("installed")
    register_accounts(site)

    urlpatterns = [path("office/", site.urls)]
    call_command("check", verbosity=0)
    call_command("migrate", verbosity=0)
    call_command("collectstatic", interactive=False, verbosity=0)
    User.objects.create_superuser("operator", password="integration-only")
    client = Client()
    assert client.get("/office/login/").status_code == 200
    assert client.login(username="operator", password="integration-only")
    assert client.get("/office/").status_code == 200
    assert client.post("/office/group/new/", {"name": "Operators"}).status_code == 302
    response = client.get("/office/group/")
    assert response.status_code == 200 and b"Operators" in response.content
    group = Group.objects.get(name="Operators")
    # The permission picker template and its markup must ship inside the wheel.
    form = client.get("/office/user/new/")
    assert form.status_code == 200 and b"ma-access-picker" in form.content
    assert (
        client.post(
            "/office/user/new/",
            {
                "username": "teller",
                "password1": "installed-smoke-passphrase",
                "password2": "installed-smoke-passphrase",
                "is_active": "on",
                "is_staff": "on",
                "groups": [str(group.pk)],
            },
        ).status_code
        == 302
    )
    assert list(User.objects.get(username="teller").groups.all()) == [group]
    assert client.post("/office/logout/").status_code == 302
    print("Installed wheel: auth, migrations, CRUD, accounts, manifest staticfiles OK")
