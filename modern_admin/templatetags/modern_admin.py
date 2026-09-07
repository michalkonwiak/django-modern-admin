from __future__ import annotations

from typing import Any

from django import forms, template
from django.forms import BoundField
from django.utils.safestring import mark_safe

register = template.Library()

ICON_PATHS: dict[str, str] = {
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "archive": '<rect width="18" height="4" x="3" y="3" rx="1"/><path d="M5 7v13h14V7M10 12h4"/>',
    "arrow-down": '<path d="m6 9 6 6 6-6"/>',
    "arrow-right": '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    "arrow-up": '<path d="m18 15-6-6-6 6"/>',
    "building-2": '<path d="M6 22V4c0-.5.4-1 1-1h10c.6 0 1 .5 1 1v18M6 12H4c-.6 0-1 .4-1 1v9M18 9h2c.6 0 1 .4 1 1v12M10 6h4M10 10h4M10 14h4M10 18h4"/>',
    "calendar": '<path d="M8 2v4M16 2v4M3 10h18"/><rect width="18" height="18" x="3" y="4" rx="2"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "circle": '<circle cx="12" cy="12" r="9"/>',
    "circle-dollar-sign": '<circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8M12 18V6"/>',
    "command": '<path d="M18 9a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3Z"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "credit-card": '<rect width="20" height="14" x="2" y="5" rx="2"/><path d="M2 10h20"/>',
    "ellipsis": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "file": '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/>',
    "filter": '<path d="M4 5h16M7 12h10M10 19h4"/>',
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6l3.5-7z"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "key": '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
    "layout-dashboard": '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9"/>',
    "package": '<path d="m7.5 4.3 9 5.15M3.3 7l8.7 5 8.7-5M12 22V12"/><path d="m21 16-9 5-9-5V8l9-5 9 5z"/>',
    "panel-left": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "pencil": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "receipt": '<path d="M4 2v20l2-2 2 2 2-2 2 2 2-2 2 2 2-2 2 2V2l-2 2-2-2-2 2-2-2-2 2-2-2-2 2Z"/><path d="M16 8h-6M16 12h-6M13 16h-3"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "settings": '<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.2a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.8v.5a2 2 0 0 1-1 1.8l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.2a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.2a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.8v-.5a2 2 0 0 1 1-1.8l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.2a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="3"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    "sparkles": '<path d="m12 3-1.9 5.1L5 10l5.1 1.9L12 17l1.9-5.1L19 10l-5.1-1.9Z"/><path d="M5 3v4M3 5h4M19 17v4M17 19h4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "zap": '<path d="M4 14a1 1 0 0 1-.8-1.6l9-10a.5.5 0 0 1 .9.4l-1.7 6.7a1 1 0 0 0 1 1.2H20a1 1 0 0 1 .8 1.6l-9 10a.5.5 0 0 1-.9-.4l1.7-6.7a1 1 0 0 0-1-1.2Z"/>',
}


@register.simple_tag
def icon(name: str, size: int = 16, css_class: str = "") -> str:
    path = ICON_PATHS.get(name, ICON_PATHS["circle"])
    return mark_safe(
        f'<svg class="ma-icon {css_class}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{path}</svg>'
    )


# Ordered most specific first: subclasses render like the base widget they extend.
WIDGET_KINDS: tuple[tuple[type[forms.Widget], str], ...] = (
    (forms.ClearableFileInput, "clearablefileinput"),
    (forms.Textarea, "textarea"),
    (forms.CheckboxSelectMultiple, "checkboxselectmultiple"),
    (forms.RadioSelect, "radioselect"),
    (forms.CheckboxInput, "checkboxinput"),
)


@register.filter
def widget_type(field: BoundField) -> str:
    widget = field.field.widget
    for widget_class, kind in WIDGET_KINDS:
        if isinstance(widget, widget_class):
            return kind
    return widget.__class__.__name__.lower()


@register.filter
def initials(value: Any) -> str:
    parts = str(value).strip().split()
    return "".join(part[0] for part in parts[:2]).upper() if parts else "?"


@register.filter
def get_item(mapping: dict[str, Any], key: str) -> Any:
    return mapping.get(key)
