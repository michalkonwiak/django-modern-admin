from pathlib import Path
from tempfile import TemporaryDirectory

from demo.config.settings import *  # noqa: F403

# A file database gives live-server request threads separate connections.
# Django shares one connection for in-memory SQLite, which is unsafe when
# independent HTMX fragments refresh concurrently.
_test_database_directory = TemporaryDirectory(prefix="modern-admin-tests-")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(Path(_test_database_directory.name) / "source.sqlite3"),
        "TEST": {"NAME": str(Path(_test_database_directory.name) / "tests.sqlite3")},
    }
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
