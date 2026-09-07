from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from playwright.sync_api import Page, expect, sync_playwright

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_workspace_login_is_styled(page: Page, live_server, width, theme):
    page.context.clear_cookies()
    page.set_viewport_size({"width": width, "height": 844})
    page.evaluate("theme => localStorage.setItem('ma-theme', theme)", theme)
    page.goto(f"{live_server.url}/app/login/", wait_until="networkidle")
    assert page.locator("form").count() == 1
    assert page.locator(".ma-auth-panel").is_visible()
    assert page.locator(".ma-auth-window").bounding_box()["width"] <= width
    field = page.locator("#id_username")
    assert field.evaluate("e => getComputedStyle(e).borderTopStyle") == "solid"
    assert field.bounding_box()["height"] >= 42
    assert field.evaluate("e => getComputedStyle(e).fontSize") == (
        "16px" if width == 390 else "13px"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("html").evaluate("e => e.classList.contains('dark')") == (theme == "dark")
    page.screenshot(path=f"/tmp/modern-admin-login-{theme}-default.png", full_page=True)
    page.locator("#id_username").fill("unknown-login-test")
    page.locator("#id_password").fill("wrong-password")
    page.get_by_role("button", name="Sign in").click()
    assert page.locator(".ma-form-alert").is_visible()
    assert page.locator("#id_username").get_attribute("class") == "ma-input"
    page.screenshot(path=f"/tmp/modern-admin-login-{theme}.png", full_page=True)


@pytest.mark.parametrize("width", [390, 1440])
def test_queue_preview_and_transition_keep_operator_on_worklist(
    page: Page, live_server, order, width
):
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(f"{live_server.url}/app/order/?queue=fulfillment", wait_until="networkidle")
    page.locator(".ma-preview-trigger").first.click()
    preview = page.locator("#record-preview")
    preview.wait_for(state="visible")
    assert "queue=fulfillment" in page.url
    bounds = preview.bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    preview.get_by_role("link", name="Mark shipped").click()
    page.locator("[data-ma-dialog]").wait_for(state="visible")
    # Escape closes only the action, preserving the underlying record workspace.
    page.keyboard.press("Escape")
    page.locator("[data-ma-dialog]").wait_for(state="detached")
    assert preview.is_visible()
    preview.get_by_role("link", name="Mark shipped").click()
    page.locator('[data-ma-dialog] button[type="submit"]').click()
    page.locator("[data-ma-dialog]").wait_for(state="detached")
    page.wait_for_function(
        "() => document.querySelector('#record-preview .ma-record-status')"
        "?.textContent.trim() === 'Shipped'"
    )
    assert preview.get_by_role("button", name="Mark shipped").is_disabled()
    page.wait_for_function("() => document.querySelectorAll('.ma-data-row').length === 0")
    assert "queue=fulfillment" in page.url
    page.keyboard.press("Escape")
    page.locator("[data-ma-preview]").wait_for(state="detached")


def test_queue_selection_survives_htmx_search(page: Page, live_server):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    page.locator('.ma-work-queues a[href*="queue=leads"]').click()
    page.wait_for_url("**queue=leads*")
    page.locator('.ma-work-queues a[aria-current="page"][href*="queue=leads"]').wait_for()
    page.wait_for_function(
        "() => !document.querySelector('#resource-panel').classList.contains('htmx-settling')"
    )
    page.fill("#resource-search", "Anna")
    page.wait_for_url("**q=Anna*")
    assert "queue=leads" in page.url
    assert page.locator(".ma-data-row").count() == 1


def assert_inside_viewport(page: Page, selector: str) -> None:
    panel = page.locator(selector).first
    panel.wait_for(state="visible")
    page.wait_for_function(
        "selector => { const r = document.querySelector(selector).getBoundingClientRect(); "
        "return r.x >= 7 && r.y >= 7 && r.right <= innerWidth - 7 "
        "&& r.bottom <= innerHeight - 7; }",
        arg=selector,
    )


@pytest.mark.parametrize("width", [320, 390, 768, 1024, 1440])
@pytest.mark.parametrize("compact", [False, True])
def test_account_popover_fits_viewport_and_tracks_resize(page: Page, live_server, width, compact):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    if compact:
        page.get_by_role("button", name="Toggle compact sidebar").click()
    page.set_viewport_size({"width": width, "height": 640})
    if width <= 760:
        page.get_by_role("button", name="Open navigation").click()
    page.get_by_role("button", name="Account menu").click()
    assert_inside_viewport(page, ".ma-user-popover")
    page.set_viewport_size({"width": width, "height": 480})
    assert_inside_viewport(page, ".ma-user-popover")
    page.keyboard.press("Escape")
    page.locator(".ma-user-popover").wait_for(state="hidden")


@pytest.mark.parametrize("dark", [False, True])
def test_popover_surfaces_match_and_stay_inside_viewport(page: Page, live_server, dark):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    if dark:
        page.get_by_role("button", name="Toggle color theme").click()
    styles = []
    for trigger, selector in [
        (".ma-choice-filter summary", ".ma-toolbar .ma-choice-options"),
        (".ma-filter-button", ".ma-range-popover"),
        (".ma-toolbar-button", ".ma-views-popover"),
        ('[aria-label="Choose columns"]', ".ma-column-picker"),
        ('[aria-label="Account menu"]', ".ma-user-popover"),
    ]:
        page.locator(trigger).first.click()
        assert_inside_viewport(page, selector)
        styles.append(
            page.locator(selector).first.evaluate(
                "e => { const s = getComputedStyle(e); return "
                "[s.backgroundColor, s.borderRadius, s.borderColor, "
                "s.boxShadow, s.backdropFilter]; }"
            )
        )
        page.keyboard.press("Escape")
        page.locator(selector).first.wait_for(state="hidden")
    assert all(style == styles[0] for style in styles)


@pytest.mark.parametrize("width", [320, 390, 768, 1024, 1440])
def test_toolbar_popovers_fit_after_open_resize_and_scroll(page: Page, live_server, width):
    page.set_viewport_size({"width": width, "height": 600})
    page.goto(f"{live_server.url}/app/customer/?status=active", wait_until="networkidle")
    for selector in [".ma-views-popover", ".ma-column-picker"]:
        panel = page.locator(selector)
        page.evaluate(
            """selector => {
            window.popoverFrames = [];
            let remaining = 20;
            const sample = () => {
                const e = document.querySelector(selector);
                const r = e.getBoundingClientRect();
                if (r.width && getComputedStyle(e).visibility !== 'hidden') {
                    window.popoverFrames.push(r.x >= 0 && r.right <= innerWidth
                        && r.y >= 0 && r.bottom <= innerHeight);
                }
                if (--remaining) requestAnimationFrame(sample);
            };
            requestAnimationFrame(sample);
        }""",
            selector,
        )
        panel.locator("xpath=preceding-sibling::button").click()
        assert_inside_viewport(page, selector)
        page.wait_for_timeout(350)
        assert page.evaluate(
            "window.popoverFrames.length > 0 && window.popoverFrames.every(Boolean)"
        )
        page.set_viewport_size({"width": 320, "height": 420})
        assert_inside_viewport(page, selector)
        page.mouse.wheel(0, 150)
        assert_inside_viewport(page, selector)
        page.keyboard.press("Escape")
        panel.wait_for(state="hidden")
        page.set_viewport_size({"width": width, "height": 600})


@pytest.mark.parametrize("dark", [False, True])
def test_record_status_uses_tonal_rectangular_labels(page: Page, live_server, dark):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    if dark:
        page.get_by_role("button", name="Toggle color theme").click()
    status = page.locator(".ma-record-status.is-success").first
    assert status.inner_text().strip() == "Active"
    assert status.evaluate("e => getComputedStyle(e).borderRadius") == "5px"
    assert status.evaluate("e => getComputedStyle(e).backdropFilter") == "none"
    assert status.evaluate("e => getComputedStyle(e).backgroundColor") != "rgba(0, 0, 0, 0)"
    assert status.locator("svg, i, .ma-record-status-mark").count() == 0
    assert status.bounding_box()["height"] == 24
    assert page.locator(".ma-table .ma-badge").count() == 0


def test_custom_checkboxes_support_keyboard_and_partial_selection(page: Page, live_server):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    checkbox = page.locator('tbody input[name="selected"]').first
    select_all = page.get_by_role("checkbox", name="Select all rows")
    assert checkbox.evaluate("e => getComputedStyle(e).appearance") == "none"
    checkbox.focus()
    page.keyboard.press("Space")
    assert checkbox.is_checked()
    page.wait_for_function("() => document.querySelector('thead input').indeterminate")
    assert page.locator(".ma-data-row.is-selected").count() == 1
    select_all.check()
    assert page.locator(".ma-data-row.is-selected").count() == 2
    page.wait_for_function("() => !document.querySelector('thead input').indeterminate")
    select_all.uncheck()
    assert page.locator(".ma-data-row.is-selected").count() == 0


def test_access_checklist_filters_toggles_and_saves(page: Page, live_server, user):
    page.goto(f"{live_server.url}/app/user/{user.pk}/edit/", wait_until="networkidle")
    permissions = page.locator(".ma-access-picker").nth(1)
    option = permissions.locator('.ma-access-option input[type="checkbox"]').first
    assert option.evaluate("e => getComputedStyle(e).appearance") == "none"
    assert permissions.locator(".ma-access-group").count() > 1

    search = permissions.locator(".ma-access-search input")
    search.fill("invoice")
    expect(permissions.locator(".ma-access-group:visible")).to_have_count(1)
    group = permissions.locator(".ma-access-group").filter(has_text="Invoice")
    visible_options = group.locator(".ma-access-option:visible")
    assert visible_options.count() == 4

    toggle = group.locator("[data-group-toggle]")
    toggle.check()
    assert permissions.locator(".ma-access-summary strong").inner_text() == "4"
    assert group.locator(".ma-access-group-count").inner_text() == "4/4"
    visible_options.first.locator("input").uncheck()
    page.wait_for_function("() => document.querySelector('[data-group-toggle]:indeterminate')")

    search.fill("nothing matches this")
    expect(permissions.locator(".ma-access-option:visible")).to_have_count(0)
    expect(permissions.locator(".ma-access-empty")).to_be_visible()

    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(f"**/app/user/{user.pk}/")
    summary = page.locator("#main-content").inner_text().lower()
    assert "change invoice" in summary and "view invoice" in summary


@pytest.fixture
def page(live_server, user, customers, order) -> Page:
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browser_path:
        pytest.skip("Set PLAYWRIGHT_BROWSERS_PATH after running `playwright install chromium`.")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{live_server.url}/login/", wait_until="domcontentloaded")
        page.fill("#id_username", "operator")
        page.fill("#id_password", "secret")
        page.click('button[type="submit"]')
        page.wait_for_url("**/app/")
        yield page
        browser.close()


def test_desktop_density_dialog_command_and_dark_mode(page: Page, live_server):
    page.goto(f"{live_server.url}/app/customer/", wait_until="domcontentloaded")
    assert page.locator("#app-sidebar").is_visible()
    assert page.locator(".ma-table tbody tr").count() == 2
    row_height = page.locator(".ma-table tbody tr").first.evaluate(
        "element => element.getBoundingClientRect().height"
    )
    assert 44 <= row_height <= 52
    assert page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()"
    )

    page.keyboard.press("Control+k")
    page.locator(".ma-command").wait_for(state="visible")
    page.wait_for_function(
        "() => document.activeElement === document.querySelector('.ma-command-input input')"
    )
    page.keyboard.press("Escape")

    page.locator(".ma-list-header .ma-button").click()
    page.wait_for_selector("[data-ma-dialog]")
    modal = page.locator("[data-ma-dialog] .ma-dialog")
    assert modal.is_visible()
    page.wait_for_function(
        "() => document.activeElement === "
        "document.querySelector('[data-ma-dialog] input:not([type=hidden])')"
    )
    page.keyboard.press("Escape")

    page.click('button[aria-label="Toggle color theme"]')
    assert page.locator("html").evaluate("element => element.classList.contains('dark')")
    page.reload(wait_until="networkidle")
    assert page.locator("html").evaluate("element => element.classList.contains('dark')")


def test_mobile_navigation_filter_drawer_and_no_document_overflow(page: Page, live_server):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_server.url}/app/customer/", wait_until="domcontentloaded")
    assert page.evaluate("document.documentElement.scrollWidth") == 390

    menu = page.locator('button[aria-label="Open navigation"]')
    assert menu.is_visible()
    menu.click()
    assert "is-open" in (page.locator("#app-sidebar").get_attribute("class") or "")

    page.locator('button[aria-label="Close navigation"]').click()
    page.locator('button[aria-label="More filters"]').click()
    page.locator(".ma-filter-drawer").wait_for(state="visible")
    assert page.locator(".ma-filter-drawer .ma-choice-filter").count() >= 1
    page.get_by_role("button", name="Close filters").click()
    assert page.locator(".ma-table-scroll").evaluate("e => e.scrollWidth === e.clientWidth")
    assert page.locator("tbody .is-identity").first.is_visible()
    assert page.locator("tbody .is-status").first.is_visible()
    assert page.locator("tbody .is-identity").first.bounding_box()["width"] >= 200
    page.get_by_role("button", name="Show all columns").click()
    assert page.locator(".ma-table-scroll").evaluate("e => e.scrollWidth > e.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth") == 390


def test_custom_filter_in_dark_mode_updates_results_and_url(page: Page, live_server):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    page.get_by_role("button", name="Toggle color theme").click()
    choice = page.locator(".ma-toolbar-filters .ma-choice-filter").first
    choice.locator("summary").click()
    choice.locator(".ma-choice-options").wait_for(state="visible")
    choice.locator('input[value="active"]').check()
    page.wait_for_url("**/*status=active*")
    assert page.locator(".ma-data-row").count() == 1
    assert page.locator(".ma-data-row").inner_text().find("Alex Morgan") >= 0


@pytest.mark.parametrize("width", [390, 1440])
def test_bulk_bar_position_does_not_change_after_selection(page: Page, live_server, width):
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    page.locator('tbody input[name="selected"]').first.check()
    bar = page.locator(".ma-bulk-bar")
    bar.wait_for(state="visible")
    first = bar.bounding_box()
    page.wait_for_timeout(1100)
    assert bar.bounding_box() == first
    assert first["x"] >= 0 and first["x"] + first["width"] <= width
    assert bar.evaluate("e => getComputedStyle(e).transform") == "none"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_command_and_drawer_dismiss_without_composited_backdrop(page: Page, live_server, theme):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    if theme == "dark":
        page.get_by_role("button", name="Toggle color theme").click()
    for _ in range(3):
        page.keyboard.press("Control+k")
        page.locator(".ma-command").wait_for(state="visible")
        for selector in [".ma-command-backdrop", ".ma-command"]:
            assert (
                page.locator(selector).evaluate("e => getComputedStyle(e).backdropFilter") == "none"
            )
        page.keyboard.press("Escape")
        page.locator(".ma-command").wait_for(state="hidden")
        page.get_by_role("button", name="More filters").click()
        page.locator(".ma-filter-drawer").wait_for(state="visible")
        assert (
            page.locator(".ma-drawer-backdrop").evaluate("e => getComputedStyle(e).backdropFilter")
            == "none"
        )
        page.keyboard.press("Escape")
        page.locator(".ma-filter-drawer").wait_for(state="hidden")
        assert page.locator("body").evaluate("e => getComputedStyle(e).overflow") != "hidden"


@pytest.mark.parametrize("dismiss", ["escape", "button", "backdrop"])
def test_dialog_dismissal_keeps_background_stable_and_restores_focus(
    page: Page, live_server, dismiss: str
):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    trigger = page.locator(".ma-list-header .ma-button")
    trigger.click()
    page.locator("[data-ma-dialog] input:not([type=hidden])").first.wait_for()
    backdrop = page.locator("[data-ma-dialog]")
    assert backdrop.evaluate("e => getComputedStyle(e).backdropFilter") == "none"
    if dismiss == "escape":
        page.keyboard.press("Escape")
    elif dismiss == "button":
        page.get_by_role("button", name="Close dialog", exact=True).click()
    else:
        backdrop.click(position={"x": 5, "y": 5})
    backdrop.wait_for(state="detached")
    assert trigger.evaluate("e => document.activeElement === e")
    trigger.click()
    page.locator("[data-ma-dialog]").wait_for(state="visible")
    page.wait_for_timeout(200)
    assert page.locator("[data-ma-dialog]").count() == 1


def test_csp_has_no_violations_and_relation_search_reaches_last_record(
    page, live_server, organization
):
    from demo.commerce.models import Organization

    def seed_relations():
        Organization.objects.bulk_create(
            [
                Organization(name=f"Search company {i:03d}", domain=f"search-{i}.example")
                for i in range(150)
            ]
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(seed_relations).result()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("""
        window.cspViolations = [];
        document.addEventListener('securitypolicyviolation', event => {
            window.cspViolations.push(event.violatedDirective + ': ' + event.blockedURI);
        });
    """)
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    picker = page.locator(".ma-toolbar-filters details[data-url]")
    picker.locator("summary").click()
    expect(picker.get_by_role("status")).to_have_text("Page 1 of 2")
    picker.get_by_role("button", name="Next", exact=True).click()
    expect(picker.get_by_role("button", name="Search company 149", exact=True)).to_be_visible()
    picker.get_by_role("searchbox").fill("Search company 149")
    expect(picker.get_by_role("status")).to_have_text("Page 1 of 1")
    picker.get_by_role("button", name="Search company 149", exact=True).click()
    page.wait_for_url("**organization=*")
    expect(page.locator(".ma-toolbar-filters details[data-url] summary")).to_contain_text(
        "Search company 149"
    )
    page.get_by_role("button", name="Toggle color theme").click()
    assert not errors
    assert page.evaluate("window.cspViolations") == []


def test_related_list_lazy_tab_edit_and_action(page, live_server, customers, order):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{live_server.url}/app/customer/{customers[0].pk}/", wait_until="networkidle")
    page.get_by_role("tab", name="Orders", exact=True).click()
    panel = page.locator("#detail-tab-panel")
    expect(panel.get_by_role("link", name=order.number, exact=True)).to_be_visible()
    panel.get_by_role("link", name="Edit", exact=True).click()
    page.wait_for_url(f"**/order/{order.pk}/edit/")
    page.go_back(wait_until="networkidle")
    page.locator("#detail-tab-panel").get_by_role("link", name="Mark shipped", exact=True).click()
    page.get_by_role("button", name="Mark shipped", exact=True).click()
    page.locator("[data-ma-dialog]").wait_for(state="detached")
    expect(
        page.locator("#detail-tab-panel").get_by_role("button", name="Mark shipped", exact=True)
    ).to_be_disabled()
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(order.refresh_from_db).result()
    assert order.status == "shipped"
    assert not errors


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_relation_popover_is_anchored_to_summary_after_resize_and_swap(page, live_server, theme):
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    if theme == "dark":
        page.get_by_role("button", name="Toggle color theme").click()
    picker = page.locator('.ma-toolbar-filters details[data-label="Organization"]')

    def assert_anchored():
        page.wait_for_function("""() => {
            const picker = document.querySelector(
                '.ma-toolbar-filters details[data-label="Organization"]'
            );
            const anchor = picker.querySelector('summary').getBoundingClientRect();
            const panel = picker.querySelector('.ma-choice-options').getBoundingClientRect();
            return Math.abs(panel.x - anchor.x) < 2 && Math.abs(panel.y - anchor.bottom - 6) < 2;
        }""")

    picker.locator("summary").click()
    expect(picker.get_by_role("button", name="Northline Labs", exact=True)).to_be_visible()
    assert_anchored()
    page.set_viewport_size({"width": 1280, "height": 900})
    assert_anchored()
    picker.get_by_role("button", name="Northline Labs", exact=True).click()
    page.wait_for_url("**organization=*")
    expect(picker.locator("summary")).to_have_text("Organization: Northline Labs")
    picker.locator("summary").click()
    expect(picker.get_by_role("button", name="Northline Labs", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    assert_anchored()
    page.keyboard.press("Escape")
    expect(picker).not_to_have_attribute("open", "")
    expect(picker.locator("summary")).to_be_focused()


@pytest.mark.parametrize("width", [390, 1440])
def test_drawer_filter_labels_track_drafts_clear_and_applied_values(page, live_server, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    page.get_by_role("button", name="More filters").click()
    drawer = page.locator(".ma-filter-drawer")
    status = drawer.locator('details[data-label="Status"]')
    relation = drawer.locator('details[data-label="Organization"]')
    status.locator("summary").click()
    status.locator('input[value="active"]').check()
    expect(status.locator("summary")).to_have_text("Status: Active")
    expect(status).to_have_class(re.compile(r"\bis-active\b"))
    assert page.url.endswith("/app/customer/")
    status.locator("summary").click()
    expect(status.locator('input[value="active"]')).to_be_checked()
    status.locator('input[value=""]').check()
    expect(status.locator("summary")).to_have_text("Status")
    expect(status).not_to_have_class(re.compile(r"\bis-active\b"))
    status.locator("summary").click()
    status.locator('input[value="active"]').check()
    relation.locator("summary").click()
    relation.get_by_role("button", name="Northline Labs", exact=True).click()
    expect(relation.locator("summary")).to_have_text("Organization: Northline Labs")
    expect(relation).to_have_class(re.compile(r"\bis-active\b"))
    relation.locator("summary").click()
    expect(relation.get_by_role("button", name="Northline Labs", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    relation.get_by_role("button", name="Any organization", exact=True).click()
    expect(relation.locator("summary")).to_have_text("Organization")
    expect(relation).not_to_have_class(re.compile(r"\bis-active\b"))
    relation.locator("summary").click()
    relation.get_by_role("button", name="Northline Labs", exact=True).click()
    drawer.get_by_role("button", name="Show results", exact=True).click()
    page.wait_for_url("**status=active*")
    assert "organization=" in page.url
    page.get_by_role("button", name="More filters").click()
    expect(status.locator("summary")).to_have_text("Status: Active")
    expect(relation.locator("summary")).to_have_text("Organization: Northline Labs")


@pytest.mark.parametrize("width", [390, 1440])
def test_select_arrow_keeps_inset_on_hover_and_focus(page, live_server, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{live_server.url}/app/settings/", wait_until="networkidle")
    select = page.locator("select.ma-input").last
    for interact in (select.hover, select.focus):
        interact()
        computed = select.evaluate("""el => {
            const style = getComputedStyle(el);
            return {appearance: style.appearance, image: style.backgroundImage,
                    size: style.backgroundSize, position: style.backgroundPosition,
                    padding: parseFloat(style.paddingRight)};
        }""")
        assert computed["appearance"] == "none"
        assert "data:image/svg+xml" in computed["image"]
        assert computed["size"] == "14px 14px"
        assert "10px" in computed["position"]
        assert computed["padding"] >= 34
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_relation_filter_survives_a_second_choice_after_an_htmx_swap(page, live_server, customers):
    """htmx builds swap fragments in a <template>, where scripting is off and
    <noscript> children parse as real inputs. A second control named after the
    filter then submitted the previously rendered value, and QueryDict.get reads
    the last one -- so the record you just clicked was silently discarded."""

    def seed_second_organization():
        from demo.commerce.models import Customer, Organization

        arc = Organization.objects.create(name="Arc Foundry", domain="arc.example")
        Customer.objects.create(name="Rowan Fisk", email="rowan@arc.example", organization=arc)

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(seed_second_organization).result()
    page.goto(f"{live_server.url}/app/customer/", wait_until="networkidle")
    picker = page.locator(".ma-toolbar-filters details[data-url]")

    picker.locator("summary").click()
    picker.get_by_role("button", name="Northline Labs", exact=True).click()
    page.wait_for_url("**organization=*")
    expect(page.locator(".ma-data-row")).to_have_count(2)

    # The panel has now been swapped in by htmx; pick a different record through it.
    picker.locator("summary").click()
    picker.get_by_role("button", name="Arc Foundry", exact=True).click()
    expect(page.locator(".ma-data-row")).to_have_count(1)
    expect(page.locator(".ma-data-row")).to_contain_text("Rowan Fisk")
    expect(picker.locator("summary")).to_have_text("Organization: Arc Foundry")

    assert page.url.count("organization=") == 1
    assert "organization=&" not in page.url and not page.url.endswith("organization=")
    assert page.locator('#resource-filters [name="organization"]').count() == 1, (
        "the swapped fragment must not resurrect a second value carrier"
    )


@pytest.mark.parametrize("width", [390, 1440])
def test_related_list_panel_stays_inside_the_page_and_scrolls_itself(
    page, live_server, customers, width
):
    def seed():
        from decimal import Decimal

        from demo.commerce.models import Order

        for _ in range(3):
            Order.objects.create(
                customer=customers[0],
                status=Order.Status.DRAFT,
                subtotal=Decimal("10"),
                total=Decimal("10"),
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(seed).result()
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(
        f"{live_server.url}/app/customer/{customers[0].pk}/?tab=orders", wait_until="networkidle"
    )
    panel = page.locator(".ma-related-panel")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("heading", name="Orders", exact=True)).to_be_visible()
    assert panel.evaluate("e => getComputedStyle(e).borderTopStyle") == "solid"
    assert panel.evaluate("e => parseFloat(getComputedStyle(e).borderRadius)") >= 8
    # The list page bleeds its table full-width; a panel must not do that.
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert panel.evaluate(
        "e => { const r = e.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; }"
    )
    if width == 390:
        assert panel.locator(".ma-table-scroll").evaluate("e => e.scrollWidth > e.clientWidth")
    # Row action labels survive; the mobile .ma-page-actions rule must not reach them.
    expect(panel.get_by_role("link", name="Edit").first).to_have_text("Edit")
    markup = page.content()
    for gone in (">LIVE<", "Live resource view", "Activity stream", "ma-live-pulse"):
        assert gone not in markup
