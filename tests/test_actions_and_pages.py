from __future__ import annotations

import json

import pytest
from django.urls import reverse

from demo.commerce.models import Activity, Customer, Order
from modern_admin.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_action_get_returns_confirmation_dialog(authenticated_client, order):
    response = authenticated_client.get(
        reverse("modern_admin:order_action", args=(order.pk, "ship")),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert b"Mark shipped" in response.content
    assert b'role="alertdialog"' in response.content


def test_action_post_executes_service_audits_and_emits_ui_events(authenticated_client, order):
    response = authenticated_client.post(
        reverse("modern_admin:order_action", args=(order.pk, "ship")),
        {"confirmed": "1"},
        HTTP_HX_REQUEST="true",
    )
    order.refresh_from_db()
    events = json.loads(response["HX-Trigger"])
    assert response.status_code == 204
    assert order.status == Order.Status.SHIPPED
    assert events["ma:toast"]["level"] == "success"
    assert events["ma:dialog-close"] == {}
    assert "#resource-detail" in events["ma:refresh"]["targets"]
    assert Activity.objects.filter(summary__contains=order.number).exists()
    assert AuditEvent.objects.filter(action="ship", resource_id=str(order.pk)).exists()


def test_unavailable_action_is_enforced_on_backend(authenticated_client, order):
    order.status = Order.Status.CANCELLED
    order.save(update_fields=("status",))
    response = authenticated_client.post(
        reverse("modern_admin:order_action", args=(order.pk, "ship")),
        {"confirmed": "1"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 422
    assert b"Only processing orders" in response.content


def test_action_validation_uses_server_form(authenticated_client, order):
    response = authenticated_client.post(
        reverse("modern_admin:order_action", args=(order.pk, "cancel")),
        {"reason": ""},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 422
    assert b"This field is required" in response.content
    order.refresh_from_db()
    assert order.status == Order.Status.PROCESSING


def test_bulk_action_only_mutates_selected_rows(authenticated_client, customers):
    response = authenticated_client.post(
        reverse("modern_admin:customer_bulk_action", args=("archive",)),
        {"selected": [customers[0].pk], "reason": "No longer in target segment"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 204
    customers[0].refresh_from_db()
    customers[1].refresh_from_db()
    assert customers[0].status == Customer.Status.INACTIVE
    assert customers[1].status == Customer.Status.LEAD


def test_dashboard_renders_configured_widgets(authenticated_client, customers, order):
    response = authenticated_client.get(reverse("modern_admin:dashboard"))
    assert response.status_code == 200
    assert b"Collected revenue" in response.content
    assert b"Recent orders" in response.content
    assert b"Customer health" in response.content


def test_custom_page_uses_shared_shell(authenticated_client):
    response = authenticated_client.get(reverse("modern_admin:page_settings"))
    assert response.status_code == 200
    assert b"Workspace settings" in response.content
    assert b'id="app-sidebar"' in response.content


def test_lazy_tab_is_a_fragment(authenticated_client, customers, order):
    response = authenticated_client.get(
        reverse("modern_admin:customer_tab", args=(customers[0].pk, "orders")),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert order.number.encode() in response.content
    assert b'id="app-sidebar"' not in response.content


def test_command_palette_searches_navigation_and_resources(authenticated_client, customers):
    response = authenticated_client.get(reverse("modern_admin:commands"), {"q": "Alex"})
    assert response.status_code == 200
    assert b"Alex Morgan" in response.content
    navigation = authenticated_client.get(reverse("modern_admin:commands"), {"q": "Orders"})
    assert b"Orders" in navigation.content
