"""Optional account administration for Django users, groups, and permissions.

Nothing here is registered implicitly: a project opts in with
`register_accounts(site)`. Django keeps ownership of authentication, password
hashing, and the permission model; this module only supplies the resource
configuration, forms, and the authorization guards that keep operators from
escalating their own access.

The bundled resources assume an `AbstractUser`-shaped model. Projects with a
different user model subclass `UserResource` and register it directly.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from django import forms
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.forms import BaseUserCreationForm, SetPasswordForm, UsernameField
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.forms import modelform_factory
from django.forms.models import ModelChoiceIterator
from django.http import HttpRequest
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from modern_admin.actions import ActionResult, ResourceAction
from modern_admin.columns import AvatarColumn, BooleanColumn, DateTimeColumn, TextColumn
from modern_admin.forms.widgets import AccessChecklist
from modern_admin.navigation import Navigation
from modern_admin.permissions import PermissionPolicy
from modern_admin.resources import ModelResource
from modern_admin.sections import DetailSection
from modern_admin.sites import ModernAdminSite
from modern_admin.sites import site as default_site

UserModel = Any


def permission_group_label(permission: Permission) -> str:
    """Group permissions by the object they protect, as Django's admin does."""
    content_type = permission.content_type
    model = content_type.model_class()
    if model is None:
        return f"{capfirst(content_type.app_label)} · {capfirst(content_type.model)}"
    options = model._meta
    return (
        f"{capfirst(str(options.app_config.verbose_name))} · {capfirst(str(options.verbose_name))}"  # noqa: E501
    )


class GroupedPermissionIterator(ModelChoiceIterator):
    """Yield permission choices as optgroups keyed by their content type."""

    def __iter__(self) -> Iterator[tuple[str, list[tuple[Any, Any]]]]:
        grouped: dict[str, list[tuple[Any, Any]]] = {}
        for permission in self.queryset.select_related("content_type"):
            grouped.setdefault(permission_group_label(permission), []).append(
                self.choice(permission)
            )
        for label in sorted(grouped):
            yield label, grouped[label]

    def __len__(self) -> int:
        return self.queryset.count()


class PermissionsField(forms.ModelMultipleChoiceField):
    """Every Django permission, grouped and searchable instead of a select box."""

    widget = AccessChecklist
    iterator = GroupedPermissionIterator

    def __init__(self, queryset: models.QuerySet[Permission] | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("required", False)
        if queryset is None:
            queryset = Permission.objects.all()
        super().__init__(queryset.order_by("content_type__app_label", "codename"), **kwargs)

    def label_from_instance(self, obj: Permission) -> str:
        return capfirst(str(obj.name).removeprefix("Can ").strip())


class GroupsField(forms.ModelMultipleChoiceField):
    """Group membership as a searchable checklist."""

    widget = AccessChecklist

    def __init__(self, queryset: models.QuerySet[Group] | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("required", False)
        if queryset is None:
            queryset = Group.objects.all()
        super().__init__(queryset.order_by("name"), **kwargs)


ACCOUNT_FIELDS: tuple[str, ...] = (
    "email",
    "first_name",
    "last_name",
    "is_active",
    "is_staff",
    "is_superuser",
    "groups",
    "user_permissions",
)
ACCESS_FIELD_CLASSES: dict[str, type[forms.Field]] = {
    "groups": GroupsField,
    "user_permissions": PermissionsField,
}


def describe_permissions(manager: Any) -> str:
    """Readable permission summary for detail pages, without Django's repr noise."""
    labels = [capfirst(str(item.name).removeprefix("Can ").strip()) for item in manager.all()[:6]]
    if not labels:
        return "—"
    return ", ".join(labels[:5]) + (", …" if len(labels) > 5 else "")


def _permission_summary(group: Group) -> str:
    total = len(group.permissions.all())
    return ngettext("%(count)d permission", "%(count)d permissions", total) % {"count": total}


def _has_field(model: type[models.Model], name: str) -> bool:
    try:
        model._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return True


class AccountFormMixin:
    """Labelling shared by the create and change account forms."""

    fields: dict[str, forms.Field]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "is_staff" in self.fields:
            self.fields["is_staff"].help_text = _(
                "Required to reach the workspace. Permissions below decide what is visible."
            )
        if "is_superuser" in self.fields:
            self.fields["is_superuser"].help_text = _(
                "Grants every permission, including the ones not listed below."
            )
        if "user_permissions" in self.fields:
            self.fields["user_permissions"].label = _("Individual permissions")


class AccountChangeForm(AccountFormMixin, forms.ModelForm):
    """Edit identity, status, and access. Passwords use the dedicated action."""


class AccountCreationForm(AccountFormMixin, BaseUserCreationForm):
    """Django's create-user form extended with the access fields."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.order_fields([self._meta.model.USERNAME_FIELD, "password1", "password2"])


def build_account_form(
    model: type[models.Model],
    *,
    creating: bool,
    allow_superuser: bool,
) -> type[forms.ModelForm[Any]]:
    """Build the account form for one model, omitting fields it does not have."""
    names = [model.USERNAME_FIELD]  # type: ignore[attr-defined]
    names += [
        name
        for name in ACCOUNT_FIELDS
        if _has_field(model, name) and (allow_superuser or name != "is_superuser")
    ]
    field_classes: dict[str, type[forms.Field]] = {
        model.USERNAME_FIELD: UsernameField,  # type: ignore[attr-defined]
        **{name: field for name, field in ACCESS_FIELD_CLASSES.items() if name in names},
    }
    return modelform_factory(
        model,
        form=AccountCreationForm if creating else AccountChangeForm,
        fields=list(dict.fromkeys(names)),
        field_classes=field_classes,
    )


class GroupForm(forms.ModelForm):
    permissions = PermissionsField(
        label=_("Permissions"),
        help_text=_("Everyone in this group receives these permissions."),
    )

    class Meta:
        model = Group
        fields = ("name", "permissions")


class AccountPolicy(PermissionPolicy[Any]):
    """Django's model permissions plus a guard against privilege escalation."""

    def can_change(self, user: Any, obj: Any = None) -> bool:
        return super().can_change(user, obj) and self.can_manage(user, obj)

    def can_delete(self, user: Any, obj: Any = None) -> bool:
        return (
            super().can_delete(user, obj)
            and self.can_manage(user, obj)
            and (obj is None or obj.pk != user.pk)
        )

    def can_manage(self, user: Any, obj: Any = None) -> bool:
        """Only superusers administer superusers, or hand out superuser status."""
        return bool(user.is_superuser or obj is None or not getattr(obj, "is_superuser", False))


class SetAccountPassword(ResourceAction[Any]):
    key = "password"
    label = _("Set password")
    description = _("Replace this account's password. The operator is not shown the old one.")
    icon = "key"
    form_class = SetPasswordForm
    placements = ("detail", "row")

    def get_form_kwargs(self, *, request: HttpRequest, obj: Any | None) -> dict[str, Any]:
        return {
            "user": obj,
            "data": request.POST if request.method == "POST" else None,
        }

    def execute(
        self, *, request: HttpRequest, obj: Any, cleaned_data: Mapping[str, Any]
    ) -> ActionResult:
        obj.set_password(cleaned_data["new_password1"])
        obj.save(update_fields=["password"])
        if obj.pk == request.user.pk:
            # Django rotates the session hash on password change; keep this operator signed in.
            update_session_auth_hash(request, obj)
        return ActionResult.success(_("Password updated for %(user)s.") % {"user": obj})


class UserResource(ModelResource[Any]):
    """Manage accounts, group membership, and individual permissions."""

    title = _("Users")
    description = _("Accounts that can reach this workspace, and what each one may see.")
    icon = "users"
    navigation = Navigation(label=_("Users"), icon="users", group=_("System"), order=20)
    permission_policy_class = AccountPolicy
    list_display = (
        AvatarColumn("username", label=_("Account"), secondary="email"),
        TextColumn("full_name", label=_("Name")),
        TextColumn("group_names", label=_("Groups")),
        BooleanColumn("is_active", label=_("Active")),
        BooleanColumn("is_staff", label=_("Workspace access")),
        BooleanColumn("is_superuser", label=_("Superuser")),
        DateTimeColumn("last_login"),
    )
    search_fields = ("username", "email", "first_name", "last_name")
    filters = ("is_active", "is_staff", "is_superuser", "groups")
    ordering = ("username",)
    page_size = 25
    actions = (SetAccountPassword,)
    detail_sections = (
        DetailSection(_("Profile"), ("username", "email", "first_name", "last_name")),
        DetailSection(
            _("Access"),
            ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
            description=_("Group membership and individual permissions decide what is visible."),
        ),
        DetailSection(_("Activity"), ("last_login", "date_joined")),
    )

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[Any]:
        return super().get_queryset(request).prefetch_related("groups")

    def full_name(self, obj: Any) -> str:
        return obj.get_full_name()

    def group_names(self, obj: Any) -> str:
        return ", ".join(group.name for group in obj.groups.all())

    def user_permissions(self, obj: Any) -> str:
        return describe_permissions(obj.user_permissions)

    def get_form_class(
        self, request: HttpRequest, obj: Any | None = None
    ) -> type[forms.ModelForm[Any]]:
        return build_account_form(
            self.model,
            creating=obj is None,
            allow_superuser=request.user.is_superuser,
        )


class GroupResource(ModelResource[Group]):
    """Reusable permission bundles, shared by any number of accounts."""

    title = _("Groups")
    description = _("Permission bundles you assign to accounts instead of one-off grants.")
    icon = "shield"
    navigation = Navigation(label=_("Groups"), icon="shield", group=_("System"), order=30)
    list_display = (
        TextColumn("name", label=_("Group"), secondary=lambda group: _permission_summary(group)),
        TextColumn("member_count", label=_("Members")),
    )
    search_fields = ("name",)
    ordering = ("name",)
    form_class = GroupForm
    detail_sections = (DetailSection(_("Group"), ("name", "permissions")),)

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[Group]:
        return (
            super()
            .get_queryset(request)
            .annotate(members=models.Count("user", distinct=True))
            .prefetch_related("permissions")
        )

    def member_count(self, obj: Group) -> int:
        return obj.members

    def permissions(self, obj: Group) -> str:
        return describe_permissions(obj.permissions)


def register_accounts(
    site: ModernAdminSite | None = None,
    *,
    user_resource: type[ModelResource[Any]] = UserResource,
    group_resource: type[ModelResource[Any]] | None = GroupResource,
) -> None:
    """Register account administration on a site. Call it from your URL module."""
    target = site or default_site
    target.register(get_user_model(), user_resource)
    if group_resource is not None:
        target.register(Group, group_resource)


__all__: Sequence[str] = (
    "AccountChangeForm",
    "AccountCreationForm",
    "AccountPolicy",
    "GroupForm",
    "GroupResource",
    "GroupsField",
    "PermissionsField",
    "SetAccountPassword",
    "UserResource",
    "build_account_form",
    "register_accounts",
)
