from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from demo.commerce import accounts, resources  # noqa: F401
from modern_admin import site

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            extra_context={"modern_admin_site": site, "site_title": site.site_title},
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("app/", site.urls),
]
