from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.db import connection
from django.db.models import Q
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from demo.commerce.models import Customer, Order
from modern_admin import ModelResource, ModernAdminSite, WorkQueue, site
from modern_admin.exceptions import InvalidResourceConfiguration
from modern_admin.models import AuditEvent, SavedView
from modern_admin.workflows import TransitionAction

pytestmark = pytest.mark.django_db


def test_work_queue_filters_search_and_preserves_selection(authenticated_client, customers):
    response = authenticated_client.get("/app/customer/?queue=leads&q=Anna", HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert response.context["paginator"].count == 1
    assert response.context["rows"][0].obj.pk == customers[1].pk
    assert b'name="queue" value="leads"' in response.content
    assert "queue=leads" in response.context["clear_search_url"]
    assert "queue=leads" in response.context["column_headers"][0]["sort_url"]


def test_queue_counts_are_scoped_and_ignore_current_search(
    authenticated_client, customers, monkeypatch
):
    resource = site.get_resource("customer")
    original = resource.get_queryset
    monkeypatch.setattr(
        resource, "get_queryset", lambda request: original(request).filter(pk=customers[1].pk)
    )
    response = authenticated_client.get("/app/customer/?q=no-match")
    counts = {queue["label"]: queue["count"] for queue in response.context["queue_links"]}
    assert counts["New leads"] == 1
    assert counts["Assigned to me"] == 1
    assert response.context["paginator"].count == 0


def test_unknown_and_forbidden_queues_are_not_silently_ignored(authenticated_client, monkeypatch):
    assert authenticated_client.get("/app/customer/?queue=missing").status_code == 404
    resource = site.get_resource("customer")
    monkeypatch.setattr(resource, "get_queues", lambda request: ())
    assert authenticated_client.get("/app/customer/?queue=leads").status_code == 404


def test_queue_permission_is_explicit():
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    assert not WorkQueue("private", "Private", Q()).has_permission(request)


def test_queue_counters_use_one_aggregate(authenticated_client, customers):
    with CaptureQueriesContext(connection) as captured:
        response = authenticated_client.get("/app/customer/")
    assert response.status_code == 200
    assert sum(query["sql"].count("FILTER (WHERE") == 3 for query in captured.captured_queries) == 1


def test_authenticated_user_cannot_access_a_restricted_queue(authenticated_client, monkeypatch):
    viewer = get_user_model().objects.create_user("viewer", is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename="view_customer"))
    authenticated_client.force_login(viewer)
    monkeypatch.setattr(
        site.get_resource("customer"),
        "queues",
        (WorkQueue("private", "Private workload", Q(), permission="commerce.change_customer"),),
    )
    response = authenticated_client.get("/app/customer/")
    assert response.status_code == 200
    assert b"Private workload" not in response.content
    assert authenticated_client.get("/app/customer/?queue=private").status_code == 404


def test_queue_callable_requires_q(user):
    request = RequestFactory().get("/")
    request.user = user
    with pytest.raises(InvalidResourceConfiguration, match="Q object"):
        WorkQueue("bad", "Bad", lambda request: None).get_condition(request)


def test_saved_view_keeps_queue(authenticated_client):
    response = authenticated_client.post(
        "/app/customer/views/save/", {"name": "My leads", "query": "queue=leads&q=Anna"}
    )
    assert response.status_code == 302
    assert "queue=leads" in SavedView.objects.get(name="My leads").query_string


def test_preview_is_scoped_permission_checked_and_progressively_enhanced(
    authenticated_client, customers, monkeypatch
):
    url = reverse("modern_admin:customer_detail", args=(customers[0].pk,))
    response = authenticated_client.get(url, {"surface": "preview"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert b'id="record-preview"' in response.content
    assert b'id="app-sidebar"' not in response.content
    assert b"Alex Morgan" in response.content
    full = authenticated_client.get(url, {"surface": "preview"})
    assert b'id="app-sidebar"' in full.content
    resource = site.get_resource("customer")
    monkeypatch.setattr(resource.permission_policy, "can_view", lambda user, obj=None: False)
    assert (
        authenticated_client.get(url, {"surface": "preview"}, HTTP_HX_REQUEST="true").status_code
        == 403
    )


def test_preview_cannot_fetch_outside_queryset(authenticated_client, customers, monkeypatch):
    resource = site.get_resource("customer")
    monkeypatch.setattr(resource, "get_queryset", lambda request: Customer.objects.none())
    assert (
        authenticated_client.get(
            f"/app/customer/{customers[0].pk}/?surface=preview", HTTP_HX_REQUEST="true"
        ).status_code
        == 404
    )


def test_preview_refresh_is_body_only(authenticated_client, order):
    response = authenticated_client.get(
        f"/app/order/{order.pk}/?surface=preview&fragment=preview", HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    assert b'id="record-preview"' in response.content
    assert b"data-ma-preview" not in response.content


def test_transition_rechecks_state_loaded_after_initial_authorization(
    authenticated_client, order, monkeypatch
):
    action = site.get_resource("order").get_action("ship")
    permission = action.has_permission
    calls = 0

    def concurrent_change(request, obj=None):
        nonlocal calls
        calls += 1
        allowed = permission(request, obj)
        if calls == 1:
            Order.objects.filter(pk=order.pk).update(status=Order.Status.CANCELLED)
        return allowed

    monkeypatch.setattr(action, "has_permission", concurrent_change)
    with patch("demo.commerce.services.mark_order_shipped") as service:
        response = authenticated_client.post(
            f"/app/order/{order.pk}/actions/ship/", {"confirmed": "1"}, HTTP_HX_REQUEST="true"
        )
    assert response.status_code == 422
    service.assert_not_called()
    assert calls == 2
    assert not AuditEvent.objects.filter(action="ship").exists()


def test_transition_can_execute_only_once_and_not_via_bulk_url(authenticated_client, order):
    url = f"/app/order/{order.pk}/actions/ship/"
    assert (
        authenticated_client.post(url, {"confirmed": "1"}, HTTP_HX_REQUEST="true").status_code
        == 204
    )
    assert (
        authenticated_client.post(url, {"confirmed": "1"}, HTTP_HX_REQUEST="true").status_code
        == 422
    )
    assert AuditEvent.objects.filter(action="ship").count() == 1
    assert (
        authenticated_client.post("/app/order/actions/ship/", {"confirmed": "1"}).status_code == 404
    )


@pytest.mark.parametrize("key", ["all", "Invalid", "two words", ""])
def test_invalid_queue_keys_fail_loudly(key):
    with pytest.raises(InvalidResourceConfiguration):
        WorkQueue(key, "Invalid", Q())


def test_duplicate_queue_keys_fail_loudly():
    class InvalidResource(ModelResource[Customer]):
        list_display = ("name",)
        queues = (WorkQueue("same", "One", Q()), WorkQueue("same", "Two", Q()))

    with pytest.raises(InvalidResourceConfiguration, match="duplicate queue"):
        InvalidResource(Customer, ModernAdminSite())


@pytest.mark.parametrize(
    "field, states, atomic",
    [
        ("missing", ("draft",), True),
        ("status", (), True),
        ("status", ("bad",), True),
        ("status", ("draft",), False),
    ],
)
def test_invalid_transition_configuration(field, states, atomic):
    action = TransitionAction[Order]()
    action.state_field, action.from_states, action.atomic = field, states, atomic
    with pytest.raises(InvalidResourceConfiguration):
        action.validate_configuration(Order)
