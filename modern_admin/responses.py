from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers


def is_htmx(request: HttpRequest) -> bool:
    return (
        request.headers.get("HX-Request", "").lower() == "true"
        and request.headers.get("HX-History-Restore-Request", "").lower() != "true"
    )


@dataclass(frozen=True, slots=True)
class Toast:
    message: str
    level: Literal["success", "info", "warning", "error"] = "success"

    def asdict(self) -> dict[str, str]:
        return {"message": str(self.message), "level": self.level}


def htmx_events(
    response: HttpResponse,
    *,
    toast: Toast | None = None,
    close_dialog: bool = False,
    refresh: tuple[str, ...] = (),
) -> HttpResponse:
    events: dict[str, object] = {}
    if toast:
        events["ma:toast"] = toast.asdict()
    if close_dialog:
        events["ma:dialog-close"] = {}
    if refresh:
        events["ma:refresh"] = {"targets": list(refresh)}
    if events:
        response["HX-Trigger"] = json.dumps(events)
    return response


def notify(request: HttpRequest, toast: Toast) -> None:
    level = {
        "success": messages.SUCCESS,
        "info": messages.INFO,
        "warning": messages.WARNING,
        "error": messages.ERROR,
    }[toast.level]
    messages.add_message(request, level, toast.message)


def render_fragment(
    request: HttpRequest,
    template_name: str,
    context: dict[str, Any],
    *,
    fragments: Mapping[str, str],
) -> HttpResponse:
    """Render only explicitly registered fragments; history restores get the shell."""
    fragment = request.GET.get("fragment")
    partial = is_htmx(request) and bool(fragment)
    if partial:
        if fragment not in fragments:
            raise Http404("Unknown page fragment")
        template_name = fragments[fragment]
    response = render(request, template_name, context)
    patch_vary_headers(response, ("HX-Request", "HX-History-Restore-Request"))
    if partial:
        params = request.GET.copy()
        params.pop("fragment", None)
        query = params.urlencode()
        response["HX-Push-Url"] = request.path + (f"?{query}" if query else "")
    return response
