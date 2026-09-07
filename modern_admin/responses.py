from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from django.contrib import messages
from django.http import HttpRequest, HttpResponse


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
