from __future__ import annotations

from typing import Any

from django.contrib.auth.forms import AuthenticationForm


class WorkspaceAuthenticationForm(AuthenticationForm):
    """Keep Django authentication and widget semantics; apply workspace styling."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            classes = field.widget.attrs.get("class", "").split()
            field.widget.attrs["class"] = " ".join(dict.fromkeys([*classes, "ma-input"]))
