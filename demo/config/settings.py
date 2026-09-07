import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = "insecure-demo-only-modern-admin-key"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "modern_admin",
    "demo.commerce",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "modern_admin.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "demo.config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "demo" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "modern_admin.csp.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
WSGI_APPLICATION = "demo.config.wsgi.application"
ASGI_APPLICATION = "demo.config.asgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "demo.sqlite3"}}
if os.environ.get("MODERN_ADMIN_POSTGRES") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("PGDATABASE", "modern_admin"),
            "USER": os.environ.get("PGUSER", "postgres"),
            "PASSWORD": os.environ.get("PGPASSWORD", ""),
            "HOST": os.environ.get("PGHOST", "127.0.0.1"),
            "PORT": os.environ.get("PGPORT", "5432"),
            "CONN_MAX_AGE": 0,
            "OPTIONS": {"connect_timeout": 10},
        }
    }
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("pl", "Polski")]
# English is the source language, so it needs no catalogue; only `pl` is compiled.
LOCALE_PATHS = [BASE_DIR / "demo" / "locale"]
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / ".static"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/login/"

# Django 6 consumes this policy natively; modern_admin.csp also supports Django 5.2.
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
