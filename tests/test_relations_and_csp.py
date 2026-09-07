import json
import re
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from demo.commerce.models import Order, Organization
from modern_admin.filters import RelationFilter
from modern_admin.sites import site

pytestmark = pytest.mark.django_db


def test_relation_search_and_pagination_reach_beyond_100(authenticated_client, customers):
    organizations = Organization.objects.bulk_create(
        [Organization(name=f"Company {i:03d}", domain=f"company-{i}.example") for i in range(150)]
    )
    endpoint = reverse("modern_admin:customer_filter_choices", args=("organization",))
    first = authenticated_client.get(endpoint).json()
    second = authenticated_client.get(endpoint, {"page": 2}).json()
    assert len(first["results"]) == 100
    assert first["has_next"] and second["has_previous"]
    last = organizations[-1]
    assert str(last.pk) in {item["value"] for item in second["results"]}
    found = authenticated_client.get(endpoint, {"q": "Company 149"}).json()
    assert found["results"] == [{"value": str(last.pk), "label": str(last)}]
    customers[0].organization = last
    customers[0].save()
    response = authenticated_client.get(
        reverse("modern_admin:customer_list"), {"organization": last.pk}
    )
    assert b"Company 149" in response.content
    assert b"Alex Morgan" in response.content
    assert b"Anna Kowalska" not in response.content


def test_relation_endpoint_uses_scoped_queryset(authenticated_client, organization, monkeypatch):
    resource = site.registry.get_for_model(Organization)
    monkeypatch.setattr(resource, "get_queryset", lambda request: Organization.objects.none())
    endpoint = reverse("modern_admin:customer_filter_choices", args=("organization",))
    assert authenticated_client.get(endpoint).json()["results"] == []


def test_relation_endpoint_permissions_and_unknown_filter(client, user):
    endpoint = reverse("modern_admin:customer_filter_choices", args=("organization",))
    assert client.get(endpoint).status_code == 302
    viewer = get_user_model().objects.create_user(username="no-permissions")
    client.force_login(viewer)
    assert client.get(endpoint).status_code == 403
    client.force_login(user)
    assert (
        client.get(reverse("modern_admin:customer_filter_choices", args=("missing",))).status_code
        == 404
    )


def test_explicit_relation_choices_are_preserved(rf, user):
    resource = site.get_resource("customer")
    request = rf.get("/")
    request.user = user
    filter_ = RelationFilter("organization", choices=(("example", "Explicit choice"),))
    filter_.bind(resource.model, resource)
    state = filter_.get_state(request, resource, request.GET)
    assert state.kind == "choice"
    assert state.options[0].label == "Explicit choice"


def test_related_list_scopes_paginates_and_links_actions(
    authenticated_client, customers, order, monkeypatch
):
    resource = site.get_resource("customer")
    tab = replace(resource.detail_tabs[0], page_size=1)
    monkeypatch.setattr(resource, "detail_tabs", (tab,))
    extra = Order.objects.create(
        customer=customers[0], status=Order.Status.PROCESSING, subtotal=10, total=10
    )
    foreign = Order.objects.create(customer=customers[1], subtotal=10, total=10)
    url = reverse("modern_admin:customer_detail", args=(customers[0].pk,))
    pages = [authenticated_client.get(url, {"tab": "orders", "related_page": n}) for n in (1, 2)]
    content = b"".join(response.content for response in pages)
    assert all(response.status_code == 200 for response in pages)
    assert reverse("modern_admin:order_edit", args=(order.pk,)).encode() in content
    assert reverse("modern_admin:order_action", args=(order.pk, "ship")).encode() in content
    assert extra.number.encode() in content
    assert foreign.number.encode() not in content
    assert b"related_page=2" in pages[0].content


def test_related_list_respects_child_permissions(
    authenticated_client, customers, order, monkeypatch
):
    child = site.get_resource("order")
    url = reverse("modern_admin:customer_tab", args=(customers[0].pk, "orders"))
    monkeypatch.setattr(child.permission_policy, "can_change", lambda *args: False)
    response = authenticated_client.get(url)
    assert b">Edit</a>" not in response.content
    assert b"/actions/" not in response.content
    monkeypatch.setattr(child.permission_policy, "can_view", lambda *args: False)
    response = authenticated_client.get(url)
    assert b"You do not have access" in response.content
    assert order.number.encode() not in response.content


def test_csp_nonce_matches_header_and_htmx_and_changes_per_response(authenticated_client):
    responses = [authenticated_client.get(reverse("modern_admin:customer_list")) for _ in range(2)]
    nonces = []
    for response in responses:
        html = response.content.decode()
        policy = response["Content-Security-Policy"]
        nonce = re.search(r'<script nonce="([^"]+)"', html)[1]
        assert f"'nonce-{nonce}'" in policy
        assert "unsafe-eval" not in policy
        assert "unsafe-inline" not in policy.split("script-src ")[1].split(";")[0]
        config = json.loads(re.search(r'name="htmx-config" content=\'([^\']+)\'', html)[1])
        assert config["allowEval"] is False
        assert config["inlineScriptNonce"] == config["inlineStyleNonce"] == nonce
        nonces.append(nonce)
    assert nonces[0] != nonces[1]


def test_repeated_blank_filter_values_never_shadow_the_selection(authenticated_client, customers):
    """A duplicated ``&key=`` used to win, so picking an option changed nothing."""
    other = Organization.objects.create(name="Arc Foundry", domain="arc.example")
    customers[1].organization = other
    customers[1].save()
    url = reverse("modern_admin:customer_list")
    query = (
        f"?ordering=-created_at&page_size=25&status=active"
        f"&organization={customers[0].organization.pk}&organization="
        f"&created_at__gte=&created_at__lte="
    )
    response = authenticated_client.get(url + query)
    assert response.status_code == 200
    assert b"Alex Morgan" in response.content
    assert b"Anna Kowalska" not in response.content
    assert response.context["page_size"] == 25
    organization_state = next(
        state for state in response.context["filter_states"] if state.key == "organization"
    )
    assert organization_state.value == str(customers[0].organization.pk)
    assert organization_state.active_label.endswith("Northline Labs")


def test_repeated_blank_values_are_dropped_from_generated_urls(authenticated_client, customers):
    url = reverse("modern_admin:customer_list")
    response = authenticated_client.get(
        url + f"?organization={customers[0].organization.pk}&organization=&page_size=25"
    )
    generated = [
        response.context["clear_search_url"],
        response.context["current_view_query"],
        *(link["url"] for link in response.context["page_links"]),
    ]
    assert all("organization=&" not in candidate for candidate in generated)
    assert all(not candidate.endswith("organization=") for candidate in generated)


def test_relation_filter_renders_a_single_control_per_key(authenticated_client, customers):
    response = authenticated_client.get(reverse("modern_admin:customer_list"))
    markup = response.content.decode()
    assert "<noscript" not in markup
    assert markup.count('name="organization"') == 2  # toolbar form + filter drawer form


def test_related_list_is_a_panel_without_a_raw_table_caption(
    authenticated_client, customers, order
):
    url = reverse("modern_admin:customer_tab", args=(customers[0].pk, "orders"))
    markup = authenticated_client.get(url).content.decode()
    assert 'class="ma-related-panel"' in markup
    assert "<h2>Orders</h2>" in markup
    # The visible caption used to render as centred, unstyled browser default text.
    assert '<caption class="ma-sr-only">' in markup
    assert "Page 1 of 1" not in markup
    assert 'class="ma-row-actions"' in markup


def test_detail_page_drops_the_live_workspace_chrome(authenticated_client, customers):
    url = reverse("modern_admin:customer_detail", args=(customers[0].pk,))
    markup = authenticated_client.get(url).content.decode()
    for gone in (
        ">LIVE<",
        "Live resource view",
        "Activity stream",
        "ma-live-pulse",
        "ma-tab-context",
    ):
        assert gone not in markup
    assert "<h2>Activity</h2>" in markup
