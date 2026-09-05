"""Site boundary shared by generated and custom resource endpoints."""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Any

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.utils.cache import add_never_cache_headers, patch_vary_headers

if TYPE_CHECKING:
    from collections.abc import Callable

    from modern_admin.sites import ModernAdminSite


def protect(
    site: ModernAdminSite, view: Callable[..., HttpResponse]
) -> Callable[..., HttpResponse]:
    @wraps(view)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            response = redirect_to_login(request.get_full_path(), site.reverse("login"))
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse(headers={"HX-Redirect": response.url}, status=200)
        elif not site.has_permission(request):
            response = HttpResponse("You do not have access to this workspace.", status=403)
        else:
            response = view(request, *args, **kwargs)
        add_never_cache_headers(response)
        patch_vary_headers(response, ("Cookie", "HX-Request", "HX-History-Restore-Request"))
        return response

    return wrapped
