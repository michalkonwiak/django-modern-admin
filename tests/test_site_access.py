import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import path

from demo.commerce.models import Customer
from modern_admin import ModelResource
from modern_admin.sites import ModernAdminSite

standalone = ModernAdminSite("independent")
standalone.register(Customer, ModelResource)
urlpatterns = [path("office/", standalone.urls)]
pytestmark = pytest.mark.django_db


@override_settings(ROOT_URLCONF=__name__)
def test_namespaced_login_without_project_auth_urls(client, user):
    response = client.get("/office/")
    assert response.status_code == 302
    assert response.url.startswith("/office/login/")
    login = client.get("/office/login/")
    assert login.status_code == 200
    assert b"ma-auth-panel" in login.content
    assert b'class="ma-input"' in login.content
    assert b"modern_admin/app.css" in login.content
    client.force_login(user)
    response = client.get("/office/customer/")
    assert response.status_code == 200
    assert b"/office/logout/" in response.content
    assert "no-store" in response.headers["Cache-Control"]
    assert client.get("/office/customer/new/").status_code == 404
    assert client.post("/office/logout/").status_code == 302


def test_nonstaff_user_cannot_enter_workspace(client):
    user = get_user_model().objects.create_user("outsider", password="secret")
    client.force_login(user)
    assert client.get("/app/").status_code == 403


@override_settings(ROOT_URLCONF=__name__)
def test_expired_htmx_session_redirects_whole_page(client):
    response = client.get("/office/customer/", HTTP_HX_REQUEST="true")
    assert response.headers["HX-Redirect"].startswith("/office/login/")


@override_settings(ROOT_URLCONF=__name__)
def test_history_restore_returns_document(client, user):
    client.force_login(user)
    response = client.get(
        "/office/customer/", HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true"
    )
    assert b"<!doctype html>" in response.content


@override_settings(ROOT_URLCONF=__name__)
def test_logout_requires_csrf_and_post(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.get("/office/logout/").status_code == 405
    assert client.post("/office/logout/").status_code == 403
