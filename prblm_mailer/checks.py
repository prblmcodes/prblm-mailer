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

    # The opt-in link is django-newsletter's, built from the Site row rather than
    # from WAGTAILADMIN_BASE_URL — so a placeholder domain here sends out dead
    # https://example.com/... confirmations even when everything else is right.
    issues.extend(_site_domain_issues())

    # NEWSLETTER_USE_HTTPS defaults to True, which breaks the link on a plain-http
    # dev server: the confirmation URL comes out https://localhost:8000/... .
    base = (getattr(settings, "WAGTAILADMIN_BASE_URL", "") or "")
    if base.startswith("http://") and getattr(settings, "NEWSLETTER_USE_HTTPS", True):
        issues.append(Warning(
            "prblm-mailer: NEWSLETTER_USE_HTTPS is on, but WAGTAILADMIN_BASE_URL is http.",
            hint="django-newsletter would build https:// confirmation links for an http "
                 "site, which won't open. Set NEWSLETTER_USE_HTTPS = not DEBUG.",
            id="prblm_mailer.W003",
        ))

    # The bundle must be mounted *above* Wagtail's catch-all. Below it, Wagtail's
    # page-serve pattern swallows every newsletter URL made only of word segments —
    # so the activation link (which contains an email address, and so doesn't match)
    # works, while the "activation completed" page it redirects to 404s.
    issues.extend(_url_ordering_issues())

    return issues


def _url_ordering_issues():
    """Warn when something else answers the newsletter URLs.

    Checked by resolving the real path rather than reading urlpatterns, so a host
    that mounted the pieces at custom prefixes is judged on what actually happens.
    """
    from django.urls import Resolver404, resolve, reverse
    from django.urls.exceptions import NoReverseMatch

    try:
        path = reverse("newsletter_list")
    except NoReverseMatch:
        return [Warning(
            "prblm-mailer: django-newsletter's URLs are not mounted.",
            hint="Confirmation and unsubscribe links need them. Add "
                 "path('', include('prblm_mailer.urls_bundle')) to urls.py.",
            id="prblm_mailer.W004",
        )]
    except Exception:  # noqa: BLE001 — URLConf not importable yet; not ours to report
        return []

    try:
        match = resolve(path)
    except (Resolver404, Exception):  # noqa: BLE001
        return []

    if getattr(match.func, "__module__", "").startswith("newsletter"):
        return []

    return [Warning(
        f"prblm-mailer: {path} is handled by {match.func.__module__}, not django-newsletter.",
        hint="Another URL pattern is shadowing it — usually Wagtail's catch-all "
             "include(wagtail_urls), which matches any path of plain word segments. "
             "Move path('', include('prblm_mailer.urls_bundle')) ABOVE it in urls.py. "
             "Symptom: the activation link works (it contains an email address, so the "
             "catch-all misses it) but the page it redirects to 404s.",
        id="prblm_mailer.W004",
    )]


def _site_domain_issues():
    """Warn while the Site row is still Django's placeholder.

    Wrapped in try/except because checks run before migrations on a fresh database,
    where django_site doesn't exist yet — a check must never be the thing that stops
    you migrating.
    """
    from .subscriptions import PLACEHOLDER_DOMAIN

    try:
        from django.contrib.sites.models import Site

        site = Site.objects.get_current()
    except Exception:  # noqa: BLE001 — no table yet, or no SITE_ID; E001 covers that
        return []

    if site.domain != PLACEHOLDER_DOMAIN:
        return []
    return [Warning(
        f"prblm-mailer: the Site domain is still {PLACEHOLDER_DOMAIN!r}.",
        hint="django-newsletter builds opt-in confirmation links from this row, so they "
             "will point at example.com. Set the domain in the admin (Sites), or set "
             "WAGTAILADMIN_BASE_URL and the package will correct it on the next signup.",
        id="prblm_mailer.W002",
    )]
