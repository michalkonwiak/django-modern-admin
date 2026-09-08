from __future__ import annotations

import warnings

import pytest
from django.template import RequestContext, Template
from django.test import RequestFactory
from django.urls import reverse

from demo.commerce.models import Customer
from demo.commerce.resources import CustomerResource, SettingsPage
from modern_admin.columns import Cell, Column, TemplateColumn
from modern_admin.rendering import ColumnQueryError, ColumnQueryWarning, render_cell

pytestmark = pytest.mark.django_db


class QueryingColumn(Column):
    def get_cell(self, obj, resource, request):
        return Cell(display=str(Customer.objects.count()))


@pytest.mark.parametrize("mode", ["warn", "error", "off"])
def test_custom_column_guard_in_list(authenticated_client, customers, monkeypatch, settings, mode):
    settings.MODERN_ADMIN_COLUMN_QUERIES = mode
    monkeypatch.setattr(
        CustomerResource, "get_list_display", lambda self, request: (QueryingColumn("name"),)
    )
    url = reverse("modern_admin:customer_list")
    if mode == "error":
        with pytest.raises(ColumnQueryError, match=r"CustomerResource.name"):
            authenticated_client.get(url)
    elif mode == "warn":
        with pytest.warns(ColumnQueryWarning, match=r"CustomerResource.name"):
            assert authenticated_client.get(url).status_code == 200
    else:
        with warnings.catch_warnings(record=True) as caught:
            assert authenticated_client.get(url).status_code == 200
        assert not [w for w in caught if issubclass(w.category, ColumnQueryWarning)]


def templates(settings, mapping):
    settings.TEMPLATES = [{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "OPTIONS": {
            "loaders": [("django.template.loaders.locmem.Loader", mapping)],
            "libraries": {"modern_admin": "modern_admin.templatetags.modern_admin"},
        },
    }]


def test_template_column_detects_lazy_relation_and_allows_eager_loading(settings, customers):
    settings.MODERN_ADMIN_COLUMN_QUERIES = "error"
    templates(settings, {"cell.html": "{{ object.organization.name }}"})
    column = TemplateColumn("name", template_name="cell.html")
    request = RequestFactory().get("/")
    resource = object()
    with pytest.raises(ColumnQueryError):
        render_cell(column, Customer.objects.get(pk=customers[0].pk), resource, request)
    obj = Customer.objects.select_related("organization").get(pk=customers[0].pk)
    assert render_cell(column, obj, resource, request).display == "Northline Labs"


def test_debug_enables_warning_by_default(settings, customers):
    settings.DEBUG = True
    with pytest.warns(ColumnQueryWarning):
        render_cell(QueryingColumn("name"), customers[0], object(), RequestFactory().get("/"))


@pytest.mark.parametrize("headers,fragment,expected", [
    ({}, "results", "shell"),
    ({"HTTP_HX_REQUEST": "true"}, "results", "results"),
    ({"HTTP_HX_REQUEST": "true", "HTTP_HX_HISTORY_RESTORE_REQUEST": "true"}, "results", "shell"),
    ({"HTTP_HX_REQUEST": "true", "HTTP_HX_TARGET": "results"}, "", "shell"),
])
def test_page_fragment_contract(
    authenticated_client, monkeypatch, settings, headers, fragment, expected,
):
    templates(settings, {"page.html": "shell", "results.html": "results"})
    monkeypatch.setattr(SettingsPage, "template_name", "page.html")
    monkeypatch.setattr(SettingsPage, "fragments", {"results": "results.html"})
    url = reverse("modern_admin:page_settings")
    response = authenticated_client.get(
        url, {"fragment": fragment, "q": "new", "tag": ["a", "b"]}, **headers,
    )
    assert response.status_code == 200
    assert response.content.decode() == expected
    if expected == "results":
        assert response["HX-Push-Url"] == url + "?q=new&tag=a&tag=b"
    else:
        assert "HX-Push-Url" not in response
    assert "HX-History-Restore-Request" in response["Vary"]


def test_unknown_page_fragment_returns_404(authenticated_client):
    response = authenticated_client.get(
        reverse("modern_admin:page_settings"), {"fragment": "unknown"}, HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 404


def test_shared_form_uses_canonical_url_and_escapes_attributes():
    request = RequestFactory().get('/report/?q=old&fragment=results')
    html = Template(
        '{% load modern_admin %}<form {% fragment_form "#results" "results" %}>'
        '<input name="q"></form>'
    ).render(RequestContext(request))
    assert 'action="/report/"' in html
    assert 'hx-get="/report/"' in html
    assert 'method="get"' in html
    assert 'hx-sync="this:replace"' in html
    assert 'hx-push-url="true"' in html
    assert 'input delay:250ms' in html
    assert 'hx-vals="{&quot;fragment&quot;: &quot;results&quot;}"' in html
    assert 'q=old' not in html


def test_form_in_widget_can_target_owning_page():
    request = RequestFactory().get('/widgets/report/')
    html = Template(
        '{% load modern_admin %}'
        '<form {% fragment_form "#results" "results" url=page_url %}></form>'
    ).render(RequestContext(request, {"page_url": '/report/?label="safe"&x=1'}))
    assert 'action="/report/?label=&quot;safe&quot;&amp;x=1"' in html
    assert '/widgets/report/' not in html


def test_strict_guard_is_removed_after_exception(settings, customers):
    settings.MODERN_ADMIN_COLUMN_QUERIES = "error"
    with pytest.raises(ColumnQueryError):
        render_cell(QueryingColumn("name"), customers[0], object(), RequestFactory().get("/"))
    assert Customer.objects.count() == 2
