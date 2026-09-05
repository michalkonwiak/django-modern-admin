from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.http import HttpRequest

if TYPE_CHECKING:
    from modern_admin.sites import ModernAdminSite

BadgeValue = str | int | Callable[[HttpRequest], str | int | None] | None


@dataclass(frozen=True, slots=True)
class Navigation:
    label: str | None = None
    icon: str = "circle"
    group: str = "Workspace"
    order: int = 100
    badge: BadgeValue = None


@dataclass(frozen=True, slots=True)
class NavigationItem:
    label: str
    icon: str
    url_name: str
    group: str = "Workspace"
    order: int = 100
    badge: BadgeValue = None
    permission: Callable[[HttpRequest], bool] | None = None

    def is_visible(self, request: HttpRequest) -> bool:
        return self.permission(request) if self.permission else True

    def get_badge(self, request: HttpRequest) -> str | int | None:
        return self.badge(request) if callable(self.badge) else self.badge


@dataclass(frozen=True, slots=True)
class ResolvedNavigationItem:
    label: str
    icon: str
    url: str
    group: str
    order: int
    badge: str | int | None = None
    active: bool = False


class NavigationRegistry:
    def __init__(self) -> None:
        self._items: list[NavigationItem] = []

    def register(self, item: NavigationItem) -> NavigationItem:
        self._items.append(item)
        return item

    @property
    def items(self) -> tuple[NavigationItem, ...]:
        return tuple(self._items)

    def resolve(
        self,
        request: HttpRequest,
        site: ModernAdminSite,
    ) -> list[ResolvedNavigationItem]:
        from django.urls import NoReverseMatch, reverse

        result: list[ResolvedNavigationItem] = []
        for item in self._items:
            if not item.is_visible(request):
                continue
            try:
                url = reverse(item.url_name)
            except NoReverseMatch:
                url = reverse(f"{site.name}:{item.url_name}")
            result.append(
                ResolvedNavigationItem(
                    label=item.label,
                    icon=item.icon,
                    url=url,
                    group=item.group,
                    order=item.order,
                    badge=item.get_badge(request),
                    active=request.path.startswith(url),
                )
            )
        return result
