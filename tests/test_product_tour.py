from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse

from modern_admin.access import protect
from modern_admin.models import ProductTourState
from modern_admin.sites import ModernAdminSite
from modern_admin.tours import product_tour_view

pytestmark = pytest.mark.django_db


def test_first_visit_is_read_only_and_available_on_custom_pages(authenticated_client, user):
    response = authenticated_client.get(reverse("modern_admin:page_settings"))
    assert b"data-ma-tour " in response.content
    assert b"data-ma-tour-start" in response.content
    dashboard = authenticated_client.get(reverse("modern_admin:dashboard"))
    assert b"data-ma-tour-start" not in dashboard.content
    assert authenticated_client.get(reverse("modern_admin:product_tour")).json() == {"show": True}
    assert not ProductTourState.objects.filter(user=user).exists()


@pytest.mark.parametrize("outcome", ["completed", "dismissed"])
def test_decision_persists_across_sessions_and_is_idempotent(authenticated_client, user, outcome):
    url = reverse("modern_admin:product_tour")
    assert authenticated_client.post(url, {"outcome": outcome}).status_code == 204
    state = ProductTourState.objects.get(user=user)
    authenticated_client.post(url, {"outcome": "completed"})
    state.refresh_from_db()
    assert state.outcome == outcome
    assert ProductTourState.objects.count() == 1
    another_browser = Client()
    another_browser.force_login(user)
    assert another_browser.get(url).json() == {"show": False}


def test_decision_is_scoped_to_account_and_site(authenticated_client, user):
    ProductTourState.objects.create(user=user, site_name="other", outcome="completed")
    other_user = get_user_model().objects.create_user(username="other")
    ProductTourState.objects.create(user=other_user, site_name="modern_admin", outcome="completed")
    url = reverse("modern_admin:product_tour")
    assert authenticated_client.get(url).json() == {"show": True}
    authenticated_client.post(
        url, {"outcome": "dismissed", "user": other_user.pk, "site_name": "evil"}
    )
    assert ProductTourState.objects.get(user=user, site_name="modern_admin").outcome == "dismissed"
    assert not ProductTourState.objects.filter(site_name="evil").exists()


def test_endpoint_enforces_authentication_permissions_csrf_and_methods(client, user):
    url = reverse("modern_admin:product_tour")
    assert client.get(url).status_code == 302
    user.is_staff = False
    user.save()
    client.force_login(user)
    assert client.post(url, {"outcome": "completed"}).status_code == 403
    user.is_staff = True
    user.save()
    secure_client = Client(enforce_csrf_checks=True)
    secure_client.force_login(user)
    assert secure_client.post(url, {"outcome": "completed"}).status_code == 403
    assert client.delete(url).status_code == 405
    assert client.post(url, {"outcome": "unknown"}).status_code == 400
    assert not ProductTourState.objects.exists()


def test_disabled_site_has_no_tour(user):
    site = ModernAdminSite()
    site.product_tour_enabled = False
    request = RequestFactory().get("/tour/")
    request.user = user
    from django.http import Http404

    with pytest.raises(Http404):
        protect(site, product_tour_view)(request, site=site)


def test_status_is_never_cached(authenticated_client):
    response = authenticated_client.get(reverse("modern_admin:product_tour"))
    assert "no-store" in response["Cache-Control"]
    assert "Cookie" in response["Vary"]


def test_polish_tour_and_disabled_shell(authenticated_client, monkeypatch):
    url = reverse("modern_admin:page_settings")
    response = authenticated_client.get(url, headers={"accept-language": "pl"})
    assert "Przewodnik po panelu" in response.content.decode()
    assert "Krok 1 z 4" in response.content.decode()
    monkeypatch.setattr(ModernAdminSite, "product_tour_enabled", False)
    assert b"data-ma-tour" not in authenticated_client.get(url).content
