from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import connection, connections
from django.db.models import Count
from django.test import RequestFactory
from django.urls import reverse

from demo.commerce.models import Activity, Customer, Order, Organization
from modern_admin import site
from modern_admin.audit import record_event
from modern_admin.models import AuditEvent
from modern_admin.views import action_view

pytestmark = pytest.mark.django_db


def test_action_handles_distinct_and_aggregated_queryset(authenticated_client, order):
    resource = site.get_resource("order")
    queryset = resource.get_queryset(RequestFactory().get("/"))
    queryset = queryset.annotate(invoice_count=Count("invoices")).distinct()
    with patch.object(resource, "get_queryset", return_value=queryset):
        response = authenticated_client.post(
            reverse("modern_admin:order_action", args=(order.pk, "ship")),
            {"confirmed": "1"},
            HTTP_HX_REQUEST="true",
        )
    assert response.status_code == 204
    order.refresh_from_db()
    assert order.status == Order.Status.SHIPPED


def test_bulk_action_with_nullable_join(authenticated_client, customers):
    Customer.objects.filter(pk=customers[0].pk).update(owner=None)
    response = authenticated_client.post(
        reverse("modern_admin:customer_bulk_action", args=("archive",)),
        {"selected": [customers[0].pk], "reason": "Archived"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 204


def test_action_rolls_back_when_audit_fails(authenticated_client, order):
    with (
        patch("modern_admin.views.record_event", side_effect=RuntimeError("audit failed")),
        pytest.raises(RuntimeError, match="audit failed"),
    ):
        authenticated_client.post(
            reverse("modern_admin:order_action", args=(order.pk, "ship")),
            {"confirmed": "1"},
            HTTP_HX_REQUEST="true",
        )
    order.refresh_from_db()
    assert order.status == Order.Status.PROCESSING
    assert not Activity.objects.exists()
    assert not AuditEvent.objects.exists()


def test_form_rolls_back_when_audit_fails(authenticated_client, organization):
    with (
        patch("modern_admin.views.record_event", side_effect=RuntimeError("audit failed")),
        pytest.raises(RuntimeError, match="audit failed"),
    ):
        authenticated_client.post(
            reverse("modern_admin:customer_create"),
            {
                "name": "Rollback",
                "email": "rollback@example.com",
                "organization": organization.pk,
                "status": Customer.Status.ACTIVE,
                "lifetime_value": "0.00",
            },
        )
    assert not Customer.objects.filter(email="rollback@example.com").exists()


def test_audit_truncates_long_labels_and_preserves_json(user, organization):
    request = RequestFactory().get("/")
    request.user = user
    with patch.object(Organization, "__str__", return_value="ą" * 300):
        event = record_event(
            request=request,
            action="checked",
            obj=organization,
            metadata={"nested": {"values": [1, True, "Łódź"]}},
        )
    event.refresh_from_db()
    assert event.object_label == "ą" * 255
    assert event.metadata == {"nested": {"values": [1, True, "Łódź"]}}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("bulk", [False, True])
def test_concurrent_actions_recheck_state_under_lock(user, order, bulk):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and independent connections")
    resource_key, action_key = ("customer", "archive") if bulk else ("order", "ship")
    resource = site.get_resource(resource_key)
    action = resource.get_action(action_key)
    barrier = Barrier(2, timeout=10)
    original_kwargs = action.get_form_kwargs

    def synchronized_kwargs(**kwargs):
        result = original_kwargs(**kwargs)
        # Both requests have read the original state before either may lock it.
        barrier.wait()
        return result

    def execute():
        try:
            request = RequestFactory().post(
                "/",
                {"selected": [order.customer_id], "reason": "Archived"}
                if bulk
                else {"confirmed": "1"},
                HTTP_HX_REQUEST="true",
            )
            request.user = user
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            return action_view(
                request,
                site=site,
                resource_key=resource_key,
                action_key=action_key,
                object_id=None if bulk else str(order.pk),
            ).status_code
        finally:
            connections.close_all()

    with (
        patch.object(action, "get_form_kwargs", side_effect=synchronized_kwargs),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        futures = [executor.submit(execute) for _ in range(2)]
        statuses = sorted(future.result(timeout=20) for future in futures)
    assert statuses == ([204, 403] if bulk else [204, 422])
    assert Activity.objects.count() == 1
    if not bulk:
        assert AuditEvent.objects.filter(action="ship").count() == 1
