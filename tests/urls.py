"""Test project URLs — Wagtail admin, the package routes, django-newsletter, anymail."""
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

urlpatterns = [
    path("admin/", include(wagtailadmin_urls)),        # + our register_admin_urls
    path("documents/", include(wagtaildocs_urls)),
    path("mailer/", include("prblm_mailer.urls")),
    path("newsletter/", include("newsletter.urls")),
    path("anymail/", include("anymail.urls")),
    path("", include(wagtail_urls)),
]
