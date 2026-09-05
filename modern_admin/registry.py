from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from typing import TYPE_CHECKING

from django.db import models

from modern_admin.exceptions import AlreadyRegistered, NotRegistered

if TYPE_CHECKING:
    from modern_admin.resources import ModelResource, PageResource


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: OrderedDict[str, ModelResource[models.Model]] = OrderedDict()
        self._models: dict[type[models.Model], ModelResource[models.Model]] = {}
        self._pages: OrderedDict[str, PageResource] = OrderedDict()

    def add_model(self, resource: ModelResource[models.Model]) -> None:
        if resource.model in self._models:
            raise AlreadyRegistered(
                f"{resource.model._meta.label} is already registered with this ModernAdminSite."
            )
        if resource.key in self._resources or resource.key in self._pages:
            raise AlreadyRegistered(f"The resource key '{resource.key}' is already registered.")
        self._resources[resource.key] = resource
        self._models[resource.model] = resource

    def add_page(self, page: PageResource) -> None:
        if page.key in self._resources or page.key in self._pages:
            raise AlreadyRegistered(f"The page key '{page.key}' is already registered.")
        self._pages[page.key] = page

    def get(self, key: str) -> ModelResource[models.Model]:
        try:
            return self._resources[key]
        except KeyError as exc:
            raise NotRegistered(f"No resource is registered with key '{key}'.") from exc

    def get_for_model(self, model: type[models.Model]) -> ModelResource[models.Model]:
        try:
            return self._models[model]
        except KeyError as exc:
            raise NotRegistered(f"{model._meta.label} is not registered.") from exc

    @property
    def resources(self) -> tuple[ModelResource[models.Model], ...]:
        return tuple(self._resources.values())

    @property
    def pages(self) -> tuple[PageResource, ...]:
        return tuple(self._pages.values())

    def __iter__(self) -> Iterator[ModelResource[models.Model]]:
        return iter(self._resources.values())
