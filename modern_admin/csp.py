"""CSP compatibility for Django 5.2; Django 6 uses its native implementation."""

import secrets

from django.conf import settings
from django.utils.functional import SimpleLazyObject

try:
    from django.middleware.csp import ContentSecurityPolicyMiddleware
    from django.template.context_processors import csp
except ImportError:

    def csp(request):
        return {"csp_nonce": getattr(request, "csp_nonce", "")}

    class ContentSecurityPolicyMiddleware:
        def __init__(self, get_response):
            self.get_response = get_response

        def __call__(self, request):
            request.csp_nonce = SimpleLazyObject(lambda: secrets.token_urlsafe(32))
            response = self.get_response(request)
            policy = getattr(settings, "SECURE_CSP", {})
            if policy and "Content-Security-Policy" not in response:
                response["Content-Security-Policy"] = "; ".join(
                    directive
                    + " "
                    + " ".join(
                        f"'nonce-{request.csp_nonce}'" if value == "<CSP_NONCE_SENTINEL>" else value
                        for value in values
                    )
                    for directive, values in policy.items()
                )
            return response


__all__ = ["ContentSecurityPolicyMiddleware", "csp"]
