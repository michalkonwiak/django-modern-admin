"""Account-scoped onboarding; mounted behind the normal site access boundary."""

from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from modern_admin.models import ProductTourState


@require_http_methods(["GET", "POST"])
def product_tour_view(request, *, site):
    if not site.product_tour_enabled:
        raise Http404
    scope = {"user": request.user, "site_name": site.name}
    if request.method == "GET":
        return JsonResponse({"show": not ProductTourState.objects.filter(**scope).exists()})
    outcome = request.POST.get("outcome")
    if outcome not in ProductTourState.Outcome.values:
        return JsonResponse({"error": "Invalid tour outcome"}, status=400)
    # A unique constraint makes retries and simultaneous tabs idempotent. A replay
    # does not overwrite the original first-run decision or its timestamp.
    ProductTourState.objects.get_or_create(**scope, defaults={"outcome": outcome})
    return HttpResponse(status=204)
