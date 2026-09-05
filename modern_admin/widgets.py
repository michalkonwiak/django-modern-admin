from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.http import HttpRequest

WidgetValue = Any | Callable[[HttpRequest], Any]


@dataclass(frozen=True, slots=True)
class Widget:
    key: str
    title: str
    template_name: str
    span: int = 1
    refresh_interval: int | None = None

    def get_context(self, request: HttpRequest) -> Mapping[str, Any]:
        return {}


@dataclass(frozen=True, slots=True)
class MetricWidget(Widget):
    value: WidgetValue = 0
    change: WidgetValue = None
    description: str = ""
    icon: str = "activity"
    template_name: str = "modern_admin/widgets/metric.html"

    def get_context(self, request: HttpRequest) -> Mapping[str, Any]:
        value = self.value(request) if callable(self.value) else self.value
        change = self.change(request) if callable(self.change) else self.change
        return {
            "value": value,
            "change": change,
            "description": self.description,
            "icon": self.icon,
        }


@dataclass(frozen=True, slots=True)
class ProgressWidget(Widget):
    value: WidgetValue = 0
    total: WidgetValue = 100
    description: str = ""
    template_name: str = "modern_admin/widgets/progress.html"

    def get_context(self, request: HttpRequest) -> Mapping[str, Any]:
        value = self.value(request) if callable(self.value) else self.value
        total = self.total(request) if callable(self.total) else self.total
        percent = min(100, round((Decimal(value) / Decimal(total)) * 100)) if total else 0
        return {"value": value, "total": total, "percent": percent, "description": self.description}


@dataclass(frozen=True, slots=True)
class TemplateWidget(Widget):
    context: Callable[[HttpRequest], Mapping[str, Any]] | None = None

    def get_context(self, request: HttpRequest) -> Mapping[str, Any]:
        return self.context(request) if self.context else {}
