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
