from __future__ import annotations

from typing import Any

from django import forms


class SwitchInput(forms.CheckboxInput):
    """Accessible checkbox styled as a switch by the Modern Admin form layer."""

    def __init__(self, attrs: dict[str, Any] | None = None, check_test=None) -> None:  # type: ignore[no-untyped-def]
        attributes = {"role": "switch", **(attrs or {})}
        super().__init__(attrs=attributes, check_test=check_test)


class MoneyInput(forms.NumberInput):
    input_type = "number"

    def __init__(
        self,
        attrs: dict[str, Any] | None = None,
        *,
        currency: str = "USD",
    ) -> None:
        attributes = {
            "step": "0.01",
            "inputmode": "decimal",
            "data-money-currency": currency,
            **(attrs or {}),
        }
        super().__init__(attributes)


class TagsInput(forms.TextInput):
    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        attributes = {
            "autocomplete": "off",
            "data-tags-input": "true",
            "placeholder": "Add comma-separated tags",
            **(attrs or {}),
        }
        super().__init__(attributes)


class AccessChecklist(forms.CheckboxSelectMultiple):
    """Searchable checkbox list for long, optionally grouped choice sets.

    Django keeps ownership of the choices, validation, and submitted values; the
    widget only adds the client-side filtering and group toggles that make large
    permission sets usable.
    """

    template_name = "modern_admin/widgets/access_checklist.html"
    group_label = ""
    search_placeholder = "Filter options…"

    def __init__(
        self,
        attrs: dict[str, Any] | None = None,
        choices: Any = (),
        *,
        group_label: str = "",
        search_placeholder: str = "",
    ) -> None:
        super().__init__(attrs=attrs, choices=choices)
        self.group_label = group_label or self.group_label
        self.search_placeholder = search_placeholder or self.search_placeholder

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:
        context = super().get_context(name, value, attrs)
        context["widget"]["group_label"] = self.group_label or name.replace("_", " ")
        context["widget"]["search_placeholder"] = self.search_placeholder
        context["widget"]["access_groups"] = self.access_groups(context["widget"]["optgroups"])
        return context

    def access_groups(self, optgroups: Any) -> list[dict[str, Any]]:
        """Ungrouped choices arrive as one optgroup each; render them as one block."""
        named: list[dict[str, Any]] = []
        ungrouped: list[Any] = []
        for group_name, options, _index in optgroups:
            if group_name:
                named.append({"name": group_name, "options": options})
            else:
                ungrouped.extend(options)
        return ([{"name": "", "options": ungrouped}] if ungrouped else []) + named
