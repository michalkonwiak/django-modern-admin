"""Diagnostics around the framework's column rendering boundary."""
from __future__ import annotations

import warnings
from contextlib import ExitStack

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connections


class ColumnQueryWarning(RuntimeWarning):
    """A column queried the database while rendering a cell."""


class ColumnQueryError(RuntimeError):
    """Strict column rendering rejected a database query."""


def render_cell(column, obj, resource, request):
    """Include overridden get_cell methods and template evaluation in the guard."""
    mode = getattr(settings, "MODERN_ADMIN_COLUMN_QUERIES", "warn" if settings.DEBUG else "off")
    if mode not in {"off", "warn", "error"}:
        raise ImproperlyConfigured("MODERN_ADMIN_COLUMN_QUERIES must be off, warn, or error")
    if mode == "off":
        return column.get_cell(obj, resource, request)

    def guard(execute, sql, params, many, context):
        message = (
            f"{type(resource).__name__}.{column.accessor} ({type(column).__name__}) "
            f"queried database {context['connection'].alias!r} while rendering a cell. "
            "Load data in get_queryset() using select_related(), prefetch_related(), "
            "or annotations before rendering."
        )
        if mode == "error":
            raise ColumnQueryError(message)
        warnings.warn(message, ColumnQueryWarning, stacklevel=3)
        return execute(sql, params, many, context)

    with ExitStack() as stack:
        for connection in connections.all():
            stack.enter_context(connection.execute_wrapper(guard))
        return column.get_cell(obj, resource, request)
