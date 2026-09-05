from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from demo.commerce.models import Customer
from modern_admin.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_resource_urls_are_predictable():
    assert reverse("modern_admin:customer_list") == "/app/customer/"
    assert reverse("modern_admin:customer_create") == "/app/customer/new/"
    assert reverse("modern_admin:customer_detail", args=(42,)) == "/app/customer/42/"
    assert reverse("modern_admin:customer_edit", args=(42,)) == "/app/customer/42/edit/"


def test_list_requires_authentication(client):
    response = client.get(reverse("modern_admin:customer_list"))
    assert response.status_code == 302
    assert "/login/" in response.url


def test_model_permission_is_enforced(client, customers):
    user_model = get_user_model()
    member = user_model.objects.create_user("member", password="secret", is_staff=True)
    client.force_login(member)
    denied = client.get(reverse("modern_admin:customer_list"))
    assert denied.status_code == 403
    member.user_permissions.add(Permission.objects.get(codename="view_customer"))
    allowed = client.get(reverse("modern_admin:customer_list"))
    assert allowed.status_code == 200
    assert b"Alex Morgan" in allowed.content
    assert b"New customer" not in allowed.content


def test_global_model_permission_also_allows_object_view(client, customers):
    user_model = get_user_model()
    member = user_model.objects.create_user("viewer", password="secret", is_staff=True)
    member.user_permissions.add(Permission.objects.get(codename="view_customer"))
    client.force_login(member)
    response = client.get(reverse("modern_admin:customer_detail", args=(customers[0].pk,)))
    assert response.status_code == 200


def test_list_search_filter_and_sort_are_url_backed(authenticated_client, customers):
    url = reverse("modern_admin:customer_list")
    response = authenticated_client.get(url, {"q": "Alex", "status": "active", "ordering": "name"})
    assert response.status_code == 200
    assert b"Alex Morgan" in response.content
    assert b"Anna Kowalska" not in response.content
    assert response.context["query"] == "Alex"
    assert response.context["active_filters"][0].active_label == "Status: Active"


def test_list_paginates_and_rejects_unlisted_page_sizes(authenticated_client, organization, user):
    for index in range(31):
        Customer.objects.create(
            name=f"Customer {index:02d}",
            email=f"customer{index}@example.com",
            organization=organization,
            owner=user,
        )
    url = reverse("modern_admin:customer_list")
    response = authenticated_client.get(url, {"page": 2, "page_size": 10})
    assert response.context["page"].number == 2
    assert len(response.context["rows"]) == 10
    rejected = authenticated_client.get(url, {"page_size": 9999})
    assert rejected.context["page_size"] == 25


def test_htmx_list_returns_panel_not_application_shell(authenticated_client, customers):
    response = authenticated_client.get(
        reverse("modern_admin:customer_list"),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert b'id="resource-panel"' in response.content
    assert b'id="app-sidebar"' not in response.content


def test_empty_state_is_actionable(authenticated_client):
    response = authenticated_client.get(reverse("modern_admin:product_list"))
    assert b"No products found" in response.content
    assert b"New product" in response.content


def test_detail_uses_sections_and_activity(authenticated_client, customers):
    response = authenticated_client.get(
        reverse("modern_admin:customer_detail", args=(customers[0].pk,))
    )
    assert response.status_code == 200
    assert b"Commercial summary" in response.content
    assert b"Orders" in response.content
    assert b"Activity" in response.content


def test_invalid_htmx_form_returns_replaceable_422(authenticated_client, organization):
    response = authenticated_client.post(
        reverse("modern_admin:customer_create"),
        {"name": "", "email": "bad", "organization": organization.pk, "surface": "dialog"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 422
    assert b"This field is required" in response.content
    assert b"data-ma-dialog" in response.content


def test_valid_create_uses_django_form_and_records_audit(authenticated_client, organization, user):
    response = authenticated_client.post(
        reverse("modern_admin:customer_create"),
        {
            "name": "Mira Stone",
            "email": "mira@example.com",
            "organization": organization.pk,
            "status": Customer.Status.ACTIVE,
            "lifetime_value": "2300.00",
            "owner": user.pk,
            "notes": "Created in test",
            "surface": "dialog",
        },
        HTTP_HX_REQUEST="true",
    )
    customer = Customer.objects.get(email="mira@example.com")
    assert response.status_code == 204
    assert response["HX-Redirect"] == reverse("modern_admin:customer_detail", args=(customer.pk,))
    assert AuditEvent.objects.filter(resource_id=str(customer.pk), action="created").exists()


def test_filter_params_are_preserved_in_sort_links(authenticated_client, customers):
    response = authenticated_client.get(
        reverse("modern_admin:customer_list"), {"q": "Alex", "status": "active"}
    )
    links = [item["sort_url"] for item in response.context["column_headers"] if item["sort_url"]]
    assert links
    assert all("q=Alex" in link and "status=active" in link for link in links)


def test_saved_view_canonicalizes_and_restores_resource_state(authenticated_client, user):
    save_url = reverse("modern_admin:customer_save_view")
    response = authenticated_client.post(
        save_url,
        {
            "name": "Healthy accounts",
            "query": "status=active&ordering=name&page=8&unexpected=ignored",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 204
    saved = user.modern_admin_saved_views.get(name="Healthy accounts")
    assert "status=active" in saved.query_string
    assert "ordering=name" in saved.query_string
    assert "page=" not in saved.query_string
    assert "unexpected" not in saved.query_string
    list_response = authenticated_client.get(reverse("modern_admin:customer_list"))
    assert list_response.context["saved_views"][0]["name"] == "Healthy accounts"
