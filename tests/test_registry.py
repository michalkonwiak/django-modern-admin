from __future__ import annotations

import pytest

from demo.commerce.models import Customer, Organization
from modern_admin import ModelResource
from modern_admin.columns import TextColumn
from modern_admin.exceptions import AlreadyRegistered, InvalidResourceConfiguration, NotRegistered
from modern_admin.sites import ModernAdminSite


def test_decorator_registration_binds_model_and_site():
    local_site = ModernAdminSite(name="local")

    @local_site.register(Customer)
    class LocalCustomerResource(ModelResource[Customer]):
        list_display = ("name",)

    resource = local_site.registry.get_for_model(Customer)
    assert resource.model is Customer
    assert resource.site is local_site
    assert resource.title == "Customers"
    assert LocalCustomerResource.__name__ == "LocalCustomerResource"


def test_direct_registration_and_duplicate_error():
    local_site = ModernAdminSite(name="local")

    class OrganizationResource(ModelResource[Organization]):
        list_display = ("name",)

    local_site.register(Organization, OrganizationResource)
    with pytest.raises(AlreadyRegistered, match="already registered"):
        local_site.register(Organization, OrganizationResource)


def test_missing_resource_has_clear_error():
    with pytest.raises(NotRegistered, match="missing"):
        ModernAdminSite().get_resource("missing")


def test_invalid_column_fails_loudly():
    local_site = ModernAdminSite()

    class BrokenResource(ModelResource[Customer]):
        list_display = (TextColumn("unknown_field"),)

    with pytest.raises(InvalidResourceConfiguration, match="Customer contains no field"):
        local_site.register(Customer, BrokenResource)


def test_invalid_search_path_names_setting_and_model():
    local_site = ModernAdminSite()

    class BrokenSearchResource(ModelResource[Customer]):
        list_display = ("name",)
        search_fields = ("organization__missing",)

    with pytest.raises(InvalidResourceConfiguration, match="search_fields.*Organization"):
        local_site.register(Customer, BrokenSearchResource)


def test_duplicate_action_keys_fail_configuration():
    from modern_admin.actions import ResourceAction

    class One(ResourceAction[Customer]):
        key = "same"

    class Two(ResourceAction[Customer]):
        key = "same"

    class BrokenActions(ModelResource[Customer]):
        list_display = ("name",)
        actions = (One, Two)

    with pytest.raises(InvalidResourceConfiguration, match="duplicate action keys"):
        ModernAdminSite().register(Customer, BrokenActions)
