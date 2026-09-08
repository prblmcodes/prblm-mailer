"""A urls.py with the bundle mounted BELOW Wagtail's catch-all — the mistake that
makes activation-completed 404 while the activation link itself works."""
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls

urlpatterns = [
    path("admin/", include(wagtailadmin_urls)),
    path("", include(wagtail_urls)),                       # catch-all, too early
    path("", include("prblm_mailer.urls_bundle")),         # never reached
]
