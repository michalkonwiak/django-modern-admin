from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from modern_admin import site
from modern_admin.accounts import AccountPolicy, PermissionsField, build_account_form

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(django_user_model):
    return django_user_model.objects.create_user(
        username="teller",
        password="secret",
        email="teller@example.com",
        is_staff=True,
    )


def permissions(*labels: str) -> list[Permission]:
    return [
        Permission.objects.get(content_type__app_label=label.split(".")[0], codename=code)
        for label, code in ((value, value.split(".")[1]) for value in labels)
    ]


def grant(user, *labels: str):
    """Grant permissions and return a fresh instance with an empty permission cache."""
    user.user_permissions.add(*permissions(*labels))
    return type(user)._default_manager.get(pk=user.pk)


def test_accounts_are_registered_with_navigation():
    reverse("modern_admin:user_list")  # resources register when the URL module loads
    user_resource = site.get_resource("user")
    group_resource = site.get_resource("group")
    assert user_resource.navigation.group == "System"
    assert group_resource.navigation.label == "Groups"
    assert isinstance(user_resource.permission_policy, AccountPolicy)


def test_user_list_requires_the_django_view_permission(client, operator):
    client.force_login(operator)
    url = reverse("modern_admin:user_list")
    assert client.get(url).status_code == 403
    grant(operator, "auth.view_user")
    assert client.get(url).status_code == 200


def navigation_labels(response) -> list[str]:
    groups = response.context["navigation_groups"].values()
    return [item.label for group in groups for item in group]


def test_navigation_only_shows_permitted_destinations(client, operator):
    client.force_login(operator)
    operator.user_permissions.add(*permissions("commerce.view_customer"))
    assert navigation_labels(client.get(reverse("modern_admin:customer_list"))) == ["Customers"]
    operator.user_permissions.add(*permissions("auth.view_user", "auth.view_group"))
    assert navigation_labels(client.get(reverse("modern_admin:customer_list"))) == [
        "Customers",
        "Users",
        "Groups",
    ]


def test_dashboard_redirects_to_the_first_permitted_page(client, operator):
    client.force_login(operator)
    operator.user_permissions.add(*permissions("commerce.view_order"))
    response = client.get(reverse("modern_admin:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("modern_admin:order_list")


def test_dashboard_without_any_destination_is_refused(client, operator):
    client.force_login(operator)
    assert client.get(reverse("modern_admin:dashboard")).status_code == 403


def test_page_permission_gates_the_settings_page(client, operator):
    client.force_login(operator)
    url = reverse("modern_admin:page_settings")
    assert client.get(url).status_code == 403
    grant(operator, "commerce.view_workspace_settings")
    assert client.get(url).status_code == 200


def test_boolean_columns_use_the_shared_status_badge(client, user):
    client.force_login(user)
    content = client.get(reverse("modern_admin:user_list")).content.decode()
    assert content.count('class="ma-record-status is-success">Yes<') >= 1
    assert "ma-boolean" not in content


def test_editing_an_account_saves_groups_and_permissions(client, user, django_user_model):
    client.force_login(user)
    group = Group.objects.create(name="Billing")
    view_invoice, change_invoice = permissions("commerce.view_invoice", "commerce.change_invoice")
    target = django_user_model.objects.create_user(username="mara", password="secret")
    response = client.post(
        reverse("modern_admin:user_edit", args=(target.pk,)),
        {
            "username": "mara",
            "email": "mara@example.com",
            "first_name": "Mara",
            "last_name": "Vos",
            "is_active": "on",
            "is_staff": "on",
            "groups": [str(group.pk)],
            "user_permissions": [str(view_invoice.pk), str(change_invoice.pk)],
        },
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.is_staff is True
    assert target.is_superuser is False
    assert list(target.groups.all()) == [group]
    assert set(target.user_permissions.all()) == {view_invoice, change_invoice}


def test_account_form_renders_the_access_checklist(client, user, django_user_model):
    client.force_login(user)
    target = django_user_model.objects.create_user(username="mara", password="secret")
    response = client.get(reverse("modern_admin:user_edit", args=(target.pk,)))
    content = response.content.decode()
    assert 'class="ma-access-picker"' in content
    assert 'class="ma-checkbox"' in content
    # Permissions are grouped by the object they protect, with the codename shown.
    assert "Authentication and Authorization · User" in content
    assert "view_invoice" in content


def test_only_superusers_may_grant_superuser_status(operator, django_user_model):
    form_class = build_account_form(
        django_user_model, creating=False, allow_superuser=operator.is_superuser
    )
    assert "is_superuser" not in form_class.base_fields
    superuser_form = build_account_form(django_user_model, creating=False, allow_superuser=True)
    assert "is_superuser" in superuser_form.base_fields


def test_superuser_accounts_are_edited_by_superusers_only(operator, user):
    policy = AccountPolicy(type(user))
    operator = grant(operator, "auth.change_user")
    assert policy.can_change(operator, operator) is True
    assert policy.can_change(operator, user) is False
    assert policy.can_change(user, operator) is True


def test_creating_an_account_sets_a_usable_password(client, user, django_user_model):
    client.force_login(user)
    response = client.post(
        reverse("modern_admin:user_create"),
        {
            "username": "newcomer",
            "password1": "correct-horse-battery",
            "password2": "correct-horse-battery",
            "email": "newcomer@example.com",
            "is_active": "on",
            "is_staff": "on",
        },
    )
    assert response.status_code == 302
    created = django_user_model.objects.get(username="newcomer")
    assert created.check_password("correct-horse-battery")
    assert created.is_staff is True


def test_set_password_action_replaces_the_password(client, user, django_user_model):
    client.force_login(user)
    target = django_user_model.objects.create_user(username="mara", password="secret")
    response = client.post(
        reverse("modern_admin:user_action", args=(target.pk, "password")),
        {"new_password1": "rotated-passphrase", "new_password2": "rotated-passphrase"},
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.check_password("rotated-passphrase")


def test_group_form_edits_permissions(client, user):
    client.force_login(user)
    group = Group.objects.create(name="Support")
    view_customer = permissions("commerce.view_customer")[0]
    response = client.post(
        reverse("modern_admin:group_edit", args=(group.pk,)),
        {"name": "Support", "permissions": [str(view_customer.pk)]},
    )
    assert response.status_code == 302
    assert list(group.permissions.all()) == [view_customer]


def test_permissions_field_groups_choices_by_content_type():
    field = PermissionsField()
    choices = dict(field.choices)
    assert "Commercial operations · Invoice" in choices
    labels = [str(label) for _value, label in choices["Commercial operations · Invoice"]]
    assert "View invoice" in labels
    assert all(not label.startswith("Can ") for label in labels)
