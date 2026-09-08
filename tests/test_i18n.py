"""Guards for the Polish/English interface.

The workspace ships one source language (English) and one catalogue (Polish).
These tests keep the two in step: a catalogue with an empty entry, or a `.mo`
that was never rebuilt, silently degrades back to English in production while
every unit test still passes.
"""

from __future__ import annotations

import gettext
import os
import pathlib
import re
import shutil
import subprocess

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import translation

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOGUES = (
    ROOT / "modern_admin/locale/pl/LC_MESSAGES/django.po",
    ROOT / "modern_admin/locale/pl/LC_MESSAGES/djangojs.po",
    ROOT / "demo/locale/pl/LC_MESSAGES/django.po",
)
ENTRY = re.compile(
    r'^msgid "(?P<id>(?:[^"\\]|\\.)*)"\n'
    r'(?:msgid_plural "(?:[^"\\]|\\.)*"\n)?'
    r'(?P<body>(?:msgstr(?:\[\d+\])? "(?:[^"\\]|\\.)*"\n)+)',
    re.M,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_active_language():
    yield
    translation.activate(settings.LANGUAGE_CODE)


@pytest.mark.parametrize("path", CATALOGUES, ids=lambda path: path.parent.parent.parent.name)
def test_every_message_is_translated(path: pathlib.Path) -> None:
    empty = re.compile(r'^msgstr(?:\[\d+\])? ""$', re.M)
    untranslated = [
        match.group("id")
        for match in ENTRY.finditer(path.read_text())
        if match.group("id") and empty.search(match.group("body"))
    ]
    assert untranslated == [], untranslated


def _assert_catalogue_current(path: pathlib.Path, generated: pathlib.Path) -> None:
    compiled = path.with_suffix(".mo")
    rebuild = f"run `python manage.py compilemessages -l pl` for {path}"
    assert compiled.exists(), rebuild
    msgfmt = shutil.which("msgfmt")
    assert msgfmt, "Install GNU gettext (msgfmt) to check compiled translation catalogues"
    subprocess.run(
        [msgfmt, "--check-format", "-o", str(generated), str(path)],
        check=True, capture_output=True, text=True,
    )
    # Compare parsed messages, including plural/context keys and metadata. Binary
    # layout can vary between gettext versions; checkout mtimes have no meaning.
    with compiled.open("rb") as stored_file, generated.open("rb") as generated_file:
        stored = gettext.GNUTranslations(stored_file)
        expected = gettext.GNUTranslations(generated_file)
    assert stored._catalog == expected._catalog, f"{compiled} is stale; {rebuild}"


@pytest.mark.parametrize("path", CATALOGUES, ids=lambda path: str(path.relative_to(ROOT)))
def test_compiled_catalogue_is_not_stale(path: pathlib.Path, tmp_path: pathlib.Path) -> None:
    # Explicitly reproduce checkout ordering: an older MO must still pass when
    # its translations match the source. Never rebuild the tracked MO in this test.
    source = tmp_path / path.name
    compiled = source.with_suffix(".mo")
    shutil.copyfile(path, source)
    shutil.copyfile(path.with_suffix(".mo"), compiled)
    os.utime(compiled, (1, 1))
    _assert_catalogue_current(source, tmp_path / "expected.mo")


def test_newer_compiled_catalogue_with_outdated_translation_fails(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "django.po"
    shutil.copyfile(CATALOGUES[0], source)
    shutil.copyfile(CATALOGUES[0].with_suffix(".mo"), source.with_suffix(".mo"))
    source.write_text(source.read_text().replace(
        'msgstr "Nie masz dostępu do tej przestrzeni roboczej."',
        'msgstr "Zmienione tłumaczenie."',
    ))
    os.utime(source, (1, 1))
    with pytest.raises(AssertionError, match="is stale"):
        _assert_catalogue_current(source, tmp_path / "expected.mo")


def test_workspace_renders_in_polish(authenticated_client, customers) -> None:
    response = authenticated_client.get("/app/customer/", headers={"accept-language": "pl"})
    assert response.status_code == 200
    body = response.content.decode()
    assert '<html lang="pl"' in body
    assert "Szukaj w przestrzeni" in body  # framework catalogue
    assert "Klienci" in body  # demo catalogue
    assert "Search workspace" not in body


def test_workspace_renders_in_english_by_default(authenticated_client, customers) -> None:
    response = authenticated_client.get("/app/customer/")
    assert response.status_code == 200
    body = response.content.decode()
    assert '<html lang="en"' in body
    assert "Search workspace" in body
    assert "Szukaj w przestrzeni" not in body


def test_switcher_stores_the_choice_for_later_requests(authenticated_client) -> None:
    response = authenticated_client.post(
        reverse("modern_admin:set_language"), {"language": "pl", "next": "/app/"}
    )
    assert response.status_code == 302
    assert response.url == "/app/"
    assert authenticated_client.cookies[settings.LANGUAGE_COOKIE_NAME].value == "pl"
    # The stored choice wins over the browser's Accept-Language header.
    body = authenticated_client.get("/app/", headers={"accept-language": "en"}).content.decode()
    assert '<html lang="pl"' in body


def test_switcher_offers_every_configured_language(authenticated_client) -> None:
    body = authenticated_client.get("/app/").content.decode()
    assert 'class="ma-language-switcher"' in body
    for code, _name in settings.LANGUAGES:
        assert f'value="{code}"' in body


def test_switcher_is_reachable_before_signing_in(client) -> None:
    body = client.get("/app/login/").content.decode()
    assert 'class="ma-language-switcher"' in body
    response = client.post(
        reverse("modern_admin:set_language"), {"language": "pl", "next": "/app/login/"}
    )
    assert response.status_code == 302
    assert "Zaloguj się" in client.get("/app/login/").content.decode()


def test_javascript_catalogue_serves_browser_strings(client) -> None:
    """Browser strings ride the active language, like every server-rendered one.

    The catalogue is JSON, so it arrives \\u-escaped; this probe stays ASCII.
    """
    url = reverse("modern_admin:javascript_catalog")
    polish = "Strona %(page)s z %(pages)s"
    assert polish not in client.get(url).content.decode()
    assert polish in client.get(url, headers={"accept-language": "pl"}).content.decode()


def test_model_metadata_follows_the_active_language(authenticated_client, customers) -> None:
    """Verbose names are resolved per request, not frozen at import time."""
    body = authenticated_client.get(
        f"/app/customer/{customers[0].pk}/", headers={"accept-language": "pl"}
    ).content.decode()
    assert "Wartość klienta" in body
    assert "Aktywny" in body
