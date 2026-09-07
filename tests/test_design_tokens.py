"""Guards for the shared type and control scales.

The stylesheets used to carry 22 different font sizes (7.5px through 56px) and
14 different control heights, so sibling controls in one toolbar row never
lined up. Everything now resolves through `--type-*` and `--control-*`.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRAMEWORK_SOURCE = ROOT / "modern_admin/static/modern_admin/src/app.css"
FRAMEWORK_BUILD = ROOT / "modern_admin/static/modern_admin/app.css"
DEMO_SOURCE = ROOT / "demo/commerce/static/commerce/demo.css"

TYPE_TOKENS = ("micro", "xs", "sm", "md", "lg", "xl", "2xl", "3xl", "display")
CONTROL_TOKENS = ("xs", "sm", "md", "lg", "xl")
# 16px on a mobile form control is what stops iOS from zooming on focus.
ALLOWED_LITERAL_SIZES = {"16px"}

FONT_SIZE = re.compile(r"font-size: ([0-9.]+px)")
CLASS_ATTRIBUTE = re.compile(r'class="([^"]*)"')
MODIFIER = re.compile(r"is-[a-z][a-z0-9-]*")
TEMPLATE_TAG = re.compile(r"{%.*?%}|{{.*?}}", re.DOTALL)
CONTROL_HEIGHT = re.compile(r"(?<![-a-z])(?:min-)?height: ([0-9.]+)px")


def test_type_and_control_tokens_are_defined() -> None:
    css = FRAMEWORK_SOURCE.read_text()
    for name in TYPE_TOKENS:
        assert f"--type-{name}:" in css, name
    for name in CONTROL_TOKENS:
        assert f"--control-{name}:" in css, name


@pytest.mark.parametrize("source", [FRAMEWORK_SOURCE, DEMO_SOURCE], ids=["framework", "demo"])
def test_font_sizes_come_from_the_type_scale(source: pathlib.Path) -> None:
    literals = set(FONT_SIZE.findall(source.read_text()))
    assert literals <= ALLOWED_LITERAL_SIZES, sorted(literals - ALLOWED_LITERAL_SIZES)


def test_interactive_controls_do_not_hardcode_a_height() -> None:
    """A control's own height comes from the scale, never from a literal.

    Containers and decorative glyphs are free to size themselves; this only
    covers the selectors a pointer actually targets.
    """
    controls = (
        ".ma-button",
        ".ma-button.is-small",
        ".ma-input",
        ".ma-icon-button",
        ".ma-search-field",
        ".ma-nav-item",
        ".ma-choice-filter summary",
        ".ma-choice-search",
        ".ma-relation-option",
        ".ma-page-size select",
        ".ma-row-menu",
        ".ma-auth-form .ma-input",
    )
    selectors = {
        line.split("{")[0].strip(): line
        for line in FRAMEWORK_SOURCE.read_text().split("\n")
        if "{" in line
    }
    unknown = [name for name in controls if name not in selectors]
    assert unknown == [], f"selectors renamed, this guard went blind: {unknown}"
    offenders = [name for name in controls if CONTROL_HEIGHT.search(selectors[name])]
    assert offenders == [], offenders


def test_built_stylesheet_is_not_stale() -> None:
    build = FRAMEWORK_BUILD.read_text()
    assert "--type-micro" in build, "run `npm run css:build`"
    assert "--control-md" in build, "run `npm run css:build`"
    assert not FONT_SIZE.findall(build) or set(FONT_SIZE.findall(build)) <= ALLOWED_LITERAL_SIZES


def test_every_component_modifier_used_in_a_template_exists_in_the_css() -> None:
    """`ma-button is-ghost` shipped for a while with no `.is-ghost` rule at all.

    A modifier that never matched anything silently fell back to the bare
    component, so the button just looked wrong and nothing complained.
    """
    css = FRAMEWORK_SOURCE.read_text() + DEMO_SOURCE.read_text()
    templates = [
        path
        for root in (ROOT / "modern_admin/templates", ROOT / "demo")
        for path in root.rglob("*.html")
    ]
    assert templates, "no templates found"
    missing: set[str] = set()
    for path in templates:
        # Drop template syntax so a branching class list reads as plain names;
        # `is-{{ variant }}` collapses to a bare `is-` and is skipped below.
        markup = TEMPLATE_TAG.sub(" ", path.read_text())
        for attribute in CLASS_ATTRIBUTE.findall(markup):
            for name in attribute.split():
                if MODIFIER.fullmatch(name) and f".{name}" not in css:
                    missing.add(f"{name} ({path.relative_to(ROOT)})")
    assert missing == set(), sorted(missing)
