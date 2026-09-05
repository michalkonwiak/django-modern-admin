from __future__ import annotations

from typing import Any

from django import forms

from modern_admin.forms.widgets import MoneyInput, TagsInput


class MoneyField(forms.DecimalField):
    def __init__(self, *args: Any, currency: str = "USD", **kwargs: Any) -> None:
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("widget", MoneyInput(currency=currency))
        super().__init__(*args, **kwargs)
        self.currency = currency


class TagsField(forms.CharField):
    widget = TagsInput

    def clean(self, value: Any) -> list[str]:
        raw = super().clean(value)
        if not raw:
            return []
        seen: set[str] = set()
        result: list[str] = []
        for item in (part.strip() for part in raw.split(",")):
            if item and item.casefold() not in seen:
                seen.add(item.casefold())
                result.append(item)
        return result
