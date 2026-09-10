from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import models
from django.test import Client
from django.urls import reverse

from demo.commerce.models import Contact, Customer, Order
from modern_admin import site
from modern_admin.models import AuditEvent

pytestmark = pytest.mark.django_db


def delete_url(obj):
    return reverse(f"modern_admin:{obj._meta.model_name}_delete", args=(obj.pk,))


def confirmation(client, obj):
    response = client.get(delete_url(obj))
    assert response.status_code == 200
    return {"confirmation": response.context["confirmation"]}


def test_confirmation_is_read_only_and_matches_existing_dialog(authenticated_client, customers):
    obj = customers[1]
    response = authenticated_client.get(delete_url(obj), HTTP_HX_REQUEST="true")
    assert b'role="alertdialog"' in response.content
    assert b"ma-button is-danger" in response.content
    assert b'id="app-sidebar"' not in response.content
    assert response.context["summary"] == (("customers", 1),)
    assert Customer.objects.filter(pk=obj.pk).exists()
    assert not AuditEvent.objects.exists()
    page = authenticated_client.get(delete_url(obj))
    assert b'id="app-sidebar"' in page.content
    assert b"hx-post=" not in page.content
    assert b"data-ma-dialog" not in page.content


@pytest.mark.parametrize("htmx", [False, True])
def test_delete_cascades_and_retains_audit_identity(authenticated_client, customers, htmx):
    obj = customers[1]
    pk = obj.pk
    Contact.objects.create(customer=obj, name="Contact")
    data = confirmation(authenticated_client, obj)
    destination = reverse("modern_admin:customer_list") + "?q=Anna&page=2"
    data["next"] = destination
    response = authenticated_client.post(
        delete_url(obj), data, **({"HTTP_HX_REQUEST": "true"} if htmx else {})
    )
    assert response.status_code == (204 if htmx else 302)
    assert (response["HX-Redirect"] if htmx else response.url) == destination
    assert not Customer.objects.filter(pk=pk).exists()
    assert not Contact.objects.exists()
    event = AuditEvent.objects.get(action="deleted")
    assert event.resource_type == "commerce.customer"
    assert event.resource_id == str(pk)
    assert event.object_label == "Anna Kowalska"
    assert b"Customer deleted successfully." in authenticated_client.get(destination).content
    assert authenticated_client.post(delete_url(obj), data).status_code == 404


@pytest.mark.parametrize("on_delete", [models.PROTECT, models.RESTRICT])
def test_protected_and_restricted_relations_are_actionable(authenticated_client, order, on_delete):
    with patch.object(Order._meta.get_field("customer").remote_field, "on_delete", on_delete):
        response = authenticated_client.get(delete_url(order.customer))
        assert response.context["blocked"]
        assert not response.context["confirmation"]
        assert b"other records depend on it" in response.content
        response = authenticated_client.post(delete_url(order.customer))
        assert response.status_code == 422
    assert Customer.objects.filter(pk=order.customer_id).exists()
    assert not AuditEvent.objects.exists()


@pytest.mark.parametrize("data", [{}, {"confirmation": "forged"}])
def test_post_requires_valid_confirmation(authenticated_client, customers, data):
    response = authenticated_client.post(delete_url(customers[1]), data)
    assert response.status_code == 422
    assert not response.context["blocked"]
    assert Customer.objects.filter(pk=customers[1].pk).exists()


def test_changed_cascade_requires_new_confirmation(authenticated_client, customers):
    obj = customers[1]
    data = confirmation(authenticated_client, obj)
    Contact.objects.create(customer=obj, name="Added after confirmation opened")
    response = authenticated_client.post(delete_url(obj), data)
    assert response.status_code == 422
    assert ("contacts", 1) in response.context["summary"]
    response = authenticated_client.post(
        delete_url(obj), {"confirmation": response.context["confirmation"]}
    )
    assert response.status_code == 302
    assert not Contact.objects.exists()


def test_confirmation_cannot_be_reused_for_another_record(authenticated_client, customers):
    data = confirmation(authenticated_client, customers[1])
    response = authenticated_client.post(delete_url(customers[0]), data)
    assert response.status_code == 422
    assert Customer.objects.count() == 2


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/",
        "//evil.example/app/customer/",
        "/app/customer/1/",
        "javascript:alert(1)",
    ],
)
def test_redirect_is_restricted_to_resource_worklist(authenticated_client, customers, target):
    obj = customers[1]
    data = confirmation(authenticated_client, obj) | {"next": target}
    response = authenticated_client.post(delete_url(obj), data)
    assert response.url == reverse("modern_admin:customer_list")


def test_model_permissions_hide_and_guard_delete(client, customers):
    member = get_user_model().objects.create_user("viewer", is_staff=True)
    member.user_permissions.add(Permission.objects.get(codename="view_customer"))
    client.force_login(member)
    obj = customers[1]
    detail = reverse("modern_admin:customer_detail", args=(obj.pk,))
    assert not client.get(detail).context["delete_url"]
    for method in (client.get, client.post):
        assert method(delete_url(obj)).status_code == 403
    member.user_permissions.add(Permission.objects.get(codename="delete_customer"))
    assert client.get(detail).context["delete_url"]
    assert client.post(delete_url(obj), confirmation(client, obj)).status_code == 302


def test_cascade_requires_related_permissions(client, customers):
    member = get_user_model().objects.create_user("deleter", is_staff=True)
    member.user_permissions.add(
        *Permission.objects.filter(codename__in=["view_customer", "delete_customer"])
    )
    client.force_login(member)
    obj = customers[1]
    Contact.objects.create(customer=obj, name="Confidential contact")
    response = client.get(delete_url(obj))
    assert response.context["blocked"]
    assert b"Confidential contact" not in response.content
    assert client.post(delete_url(obj)).status_code == 422
    member.user_permissions.add(Permission.objects.get(codename="delete_contact"))
    assert client.post(delete_url(obj), confirmation(client, obj)).status_code == 302


def test_scoped_queryset_and_disable_switch_apply_to_post(authenticated_client, customers):
    obj = customers[1]
    resource = site.get_resource("customer")
    data = confirmation(authenticated_client, obj)
    with patch.object(resource, "get_queryset", return_value=Customer.objects.exclude(pk=obj.pk)):
        assert authenticated_client.get(delete_url(obj)).status_code == 404
        assert authenticated_client.post(delete_url(obj), data).status_code == 404
    with patch.object(resource, "delete_enabled", False):
        assert authenticated_client.post(delete_url(obj), data).status_code == 403
    assert Customer.objects.filter(pk=obj.pk).exists()


def test_permission_is_rechecked_after_lock(authenticated_client, customers):
    obj = customers[1]
    data = confirmation(authenticated_client, obj)
    with patch.object(site.get_resource("customer"), "can_delete", side_effect=[True, False]):
        assert authenticated_client.post(delete_url(obj), data).status_code == 403
    assert Customer.objects.filter(pk=obj.pk).exists()


@pytest.mark.parametrize("failure", ["audit", "delete"])
def test_deletion_and_audit_roll_back_together(authenticated_client, customers, failure):
    obj = customers[1]
    data = confirmation(authenticated_client, obj)

    def fail_after_delete(request, instance):
        instance.delete()
        raise RuntimeError("failed")

    target = (
        patch("modern_admin.views.record_event", side_effect=RuntimeError("failed"))
        if failure == "audit"
        else patch.object(
            site.get_resource("customer"), "delete_object", side_effect=fail_after_delete
        )
    )
    with target, pytest.raises(RuntimeError, match="failed"):
        authenticated_client.post(delete_url(obj), data)
    assert Customer.objects.filter(pk=obj.pk).exists()
    assert not AuditEvent.objects.exists()


def test_model_delete_override_is_called(authenticated_client, customers):
    obj = customers[1]
    data = confirmation(authenticated_client, obj)
    original = Customer.delete
    with patch.object(Customer, "delete", autospec=True, side_effect=original) as delete:
        assert authenticated_client.post(delete_url(obj), data).status_code == 302
    delete.assert_called_once()


def test_delete_requires_csrf_and_rejects_other_methods(authenticated_client, customers, user):
    obj = customers[1]
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.post(delete_url(obj), confirmation(client, obj)).status_code == 403
    for method in (
        authenticated_client.delete,
        authenticated_client.put,
        authenticated_client.patch,
        authenticated_client.head,
    ):
        assert method(delete_url(obj)).status_code == 405
    assert Customer.objects.filter(pk=obj.pk).exists()


def test_self_deletion_is_forbidden(authenticated_client, user):
    assert authenticated_client.get(delete_url(user)).status_code == 403
    assert authenticated_client.post(delete_url(user)).status_code == 403


def test_polish_deletion_dialog(authenticated_client, customers):
    response = authenticated_client.get(delete_url(customers[1]), HTTP_ACCEPT_LANGUAGE="pl")
    assert "Usuń rekord" in response.content.decode()
    assert "Rekordy do usunięcia" in response.content.decode()


def test_registered_cascade_respects_its_scoped_queryset(authenticated_client, customers):
    from modern_admin.resources import ModelResource

    obj = customers[1]
    contact = Contact.objects.create(customer=obj, name="Outside scope")
    related = ModelResource(Contact, site)
    original = site.registry.get_for_model

    def resource_for_model(model):
        return related if model is Contact else original(model)

    with (
        patch.object(site.registry, "get_for_model", side_effect=resource_for_model),
        patch.object(related, "get_queryset", return_value=Contact.objects.none()),
    ):
        response = authenticated_client.post(delete_url(obj))
    assert response.status_code == 422
    assert response.context["blocked"]
    assert Contact.objects.filter(pk=contact.pk).exists()
    assert Customer.objects.filter(pk=obj.pk).exists()


def test_late_protected_error_rolls_back_audit(authenticated_client, customers):
    from django.db.models.deletion import ProtectedError

    obj = customers[1]
    data = confirmation(authenticated_client, obj)
    with patch.object(
        site.get_resource("customer"),
        "delete_object",
        side_effect=ProtectedError("Late relationship", {obj}),
    ):
        response = authenticated_client.post(delete_url(obj), data, HTTP_HX_REQUEST="true")
    assert response.status_code == 422
    assert response.context["blocked"]
    assert b'role="alertdialog"' in response.content
    assert not AuditEvent.objects.exists()
    assert Customer.objects.filter(pk=obj.pk).exists()


def test_nullable_joins_and_distinct_do_not_break_deletion(authenticated_client, customers):
    obj = customers[1]
    data = confirmation(authenticated_client, obj)
    queryset = Customer.objects.select_related("owner").distinct()
    with patch.object(site.get_resource("customer"), "get_queryset", return_value=queryset):
        response = authenticated_client.post(delete_url(obj), data)
    assert response.status_code == 302
    assert not Customer.objects.filter(pk=obj.pk).exists()
