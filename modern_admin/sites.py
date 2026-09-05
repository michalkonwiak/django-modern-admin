from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypeVar, overload

from django.db import models
from django.http import HttpRequest
from django.urls import URLPattern, include, path, reverse

from modern_admin.navigation import (
    Navigation,
    NavigationRegistry,
    ResolvedNavigationItem,
)
from modern_admin.registry import ResourceRegistry
from modern_admin.resources import Dashboard, ModelResource, PageResource

ModelT = TypeVar("ModelT", bound=models.Model)
ResourceT = TypeVar("ResourceT", bound=ModelResource[Any])
PageT = TypeVar("PageT", bound=PageResource)


class ModernAdminSite:
    site_title = "Northstar"
    site_subtitle = "Operations"
    extra_css: tuple[str, ...] = ()
    navigation_group_order: tuple[str, ...] = (
        "Workspace",
        "Relationships",
        "Operations",
        "Billing",
        "System",
    )

    def __init__(self, name: str = "modern_admin") -> None:
        self.name = name
        self.registry = ResourceRegistry()
        self.navigation = NavigationRegistry()
        self.dashboard_class: type[Dashboard] = Dashboard

    @overload
    def register(self, model: type[ModelT]) -> Callable[[type[ResourceT]], type[ResourceT]]: ...

    @overload
    def register(self, model: type[ModelT], resource_class: type[ResourceT]) -> type[ResourceT]: ...

    def register(
        self,
        model: type[ModelT],
        resource_class: type[ResourceT] | None = None,
    ) -> type[ResourceT] | Callable[[type[ResourceT]], type[ResourceT]]:
        def decorator(cls: type[ResourceT]) -> type[ResourceT]:
            resource = cls(model, self)
            self.registry.add_model(resource)
            return cls

        return decorator(resource_class) if resource_class is not None else decorator

    def page(
        self,
        *,
        path: str,
        label: str,
        icon: str = "file",
        group: str = "Workspace",
        order: int = 100,
    ) -> Callable[[type[PageT]], type[PageT]]:
        def decorator(cls: type[PageT]) -> type[PageT]:
            cls.path = path
            cls.label = label
            cls.title = cls.title or label
            cls.icon = icon
            cls.navigation = cls.navigation or Navigation(
                label=label, icon=icon, group=group, order=order
            )
            self.registry.add_page(cls(self))
            return cls

        return decorator

    def set_dashboard(self, dashboard_class: type[Dashboard]) -> type[Dashboard]:
        self.dashboard_class = dashboard_class
        return dashboard_class

    def get_resource(self, key: str) -> ModelResource[models.Model]:
        return self.registry.get(key)

    def reverse(self, name: str, *, args: tuple[Any, ...] = ()) -> str:
        return reverse(f"{self.name}:{name}", args=args)

    def has_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_active and request.user.is_staff)

    def get_navigation(self, request: HttpRequest) -> dict[str, list[ResolvedNavigationItem]]:
        items: list[ResolvedNavigationItem] = [
            ResolvedNavigationItem(
                label="Overview",
                icon="layout-dashboard",
                url=self.reverse("dashboard"),
                group="Workspace",
                order=0,
                active=request.path == self.reverse("dashboard"),
            )
        ]
        for resource in self.registry.resources:
            nav = resource.navigation
            if nav is None or not resource.permission_policy.can_view(request.user):
                continue
            url = self.reverse(f"{resource.key}_list")
            badge = nav.badge(request) if callable(nav.badge) else nav.badge
            items.append(
                ResolvedNavigationItem(
                    label=nav.label or resource.title,
                    icon=nav.icon,
                    url=url,
                    group=nav.group,
                    order=nav.order,
                    badge=badge,
                    active=request.path.startswith(url),
                )
            )
        for page in self.registry.pages:
            nav = page.navigation
            if nav is None or not page.has_permission(request):
                continue
            url = self.reverse(f"page_{page.key}")
            items.append(
                ResolvedNavigationItem(
                    label=nav.label or page.title,
                    icon=nav.icon,
                    url=url,
                    group=nav.group,
                    order=nav.order,
                    active=request.path.startswith(url),
                )
            )
        items.extend(self.navigation.resolve(request, self))
        grouped: dict[str, list[ResolvedNavigationItem]] = defaultdict(list)
        group_rank = {name: index for index, name in enumerate(self.navigation_group_order)}
        for item in sorted(
            items,
            key=lambda candidate: (
                group_rank.get(candidate.group, len(group_rank)),
                candidate.group,
                candidate.order,
            ),
        ):
            grouped[item.group].append(item)
        return dict(grouped)

    def each_context(self, request: HttpRequest) -> dict[str, Any]:
        return {
            "modern_admin_site": self,
            "site_title": self.site_title,
            "site_subtitle": self.site_subtitle,
            "navigation_groups": self.get_navigation(request),
            "logout_url": self.reverse("logout"),
        }

    def get_urls(self) -> list[URLPattern]:
        from modern_admin.views import (
            action_view,
            command_palette_view,
            dashboard_view,
            page_view,
            resource_detail_view,
            resource_form_view,
            resource_list_view,
            resource_tab_view,
            saved_view_view,
            widget_view,
        )

        patterns: list[URLPattern] = [
            path("", dashboard_view, {"site": self}, name="dashboard"),
            path("commands/", command_palette_view, {"site": self}, name="commands"),
            path("widgets/<slug:widget_key>/", widget_view, {"site": self}, name="widget"),
        ]
        for page_resource in self.registry.pages:
            patterns.append(
                path(
                    page_resource.path,
                    page_view,
                    {"site": self, "page_key": page_resource.key},
                    name=f"page_{page_resource.key}",
                )
            )
        for resource in self.registry.resources:
            key = resource.key
            custom_urls = list(resource.get_urls())
            if custom_urls:
                patterns.append(path(f"{key}/", include(custom_urls)))
            patterns.extend(
                [
                    path(
                        f"{key}/",
                        resource_list_view,
                        {"site": self, "resource_key": key},
                        name=f"{key}_list",
                    ),
                    path(
                        f"{key}/views/save/",
                        saved_view_view,
                        {"site": self, "resource_key": key},
                        name=f"{key}_save_view",
                    ),
                    path(
                        f"{key}/new/",
                        resource_form_view,
                        {"site": self, "resource_key": key},
                        name=f"{key}_create",
                    ),
                    path(
                        f"{key}/<str:object_id>/",
                        resource_detail_view,
                        {"site": self, "resource_key": key},
                        name=f"{key}_detail",
                    ),
                    path(
                        f"{key}/<str:object_id>/edit/",
                        resource_form_view,
                        {"site": self, "resource_key": key},
                        name=f"{key}_edit",
                    ),
                    path(
                        f"{key}/<str:object_id>/tabs/<slug:tab_key>/",
                        resource_tab_view,
                        {"site": self, "resource_key": key},
                        name=f"{key}_tab",
                    ),
                    path(
                        f"{key}/<str:object_id>/actions/<slug:action_key>/",
                        action_view,
                        {"site": self, "resource_key": key},
                        name=f"{key}_action",
                    ),
                    path(
                        f"{key}/actions/<slug:action_key>/",
                        action_view,
                        {"site": self, "resource_key": key, "object_id": None},
                        name=f"{key}_bulk_action",
                    ),
                ]
            )
        from django.contrib.auth.views import LoginView, LogoutView
        from django.urls import URLResolver, reverse_lazy

        from modern_admin.access import protect

        def secure(items: list[URLPattern | URLResolver]) -> list[URLPattern | URLResolver]:
            secured: list[URLPattern | URLResolver] = []
            for item in items:
                if isinstance(item, URLResolver):
                    secured.append(
                        URLResolver(
                            item.pattern,
                            secure(item.url_patterns),
                            item.default_kwargs,
                            item.app_name,
                            item.namespace,
                        )
                    )
                else:
                    secured.append(
                        URLPattern(
                            item.pattern, protect(self, item.callback), item.default_args, item.name
                        )
                    )
            return secured

        return [
            path(
                "login/",
                LoginView.as_view(
                    template_name="modern_admin/pages/login.html",
                    next_page=reverse_lazy(f"{self.name}:dashboard"),
                    extra_context={"site_title": self.site_title, "modern_admin_site": self},
                ),
                name="login",
            ),
            path(
                "logout/",
                LogoutView.as_view(next_page=reverse_lazy(f"{self.name}:login")),
                name="logout",
            ),
            *secure(patterns),
        ]

    @property
    def urls(self) -> tuple[list[URLPattern], str, str]:
        return self.get_urls(), "modern_admin", self.name


site = ModernAdminSite()
