"""Startup checks, so a missing setting fails with a clear message — not a silent
404 (unsubscribe links) or a blank image (emails), which are hard to diagnose.

Registered from apps.ready(); runs on `manage.py check` and at server start.
"""
from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def check_prblm_mailer_settings(app_configs, **kwargs):
    issues = []

    # django-newsletter is built on the sites framework and looks up "the current
    # site" via SITE_ID. Without it, confirm/unsubscribe views 404.
    if getattr(settings, "SITE_ID", None) is None:
        issues.append(Error(
            "prblm-mailer: SITE_ID is not set.",
            hint="django-newsletter uses Django's sites framework. Add "
                 "'django.contrib.sites' to INSTALLED_APPS and set SITE_ID = 1.",
            id="prblm_mailer.E001",
        ))

    # Emails need absolute URLs (links + images). We fall back to the current
    # Wagtail Site's URL when this is unset, but that can be wrong in email, so warn.
    if not (getattr(settings, "WAGTAILADMIN_BASE_URL", "") or ""):
        issues.append(Warning(
            "prblm-mailer: WAGTAILADMIN_BASE_URL is not set.",
            hint="Email links and images need an absolute URL. Without it, the current "
                 "Wagtail Site's URL is used as a fallback, which may be wrong in emails. "
                 "Set WAGTAILADMIN_BASE_URL, e.g. 'https://example.com'.",
            id="prblm_mailer.W001",
        ))

    return issues
