"""One-include URL bundle for the host site.

Mount at the site root so each piece keeps its conventional path:

    path("", include("prblm_mailer.urls_bundle")),

gives you:
    /mailer/…                       — one-click unsubscribe (this package)
    /newsletter/…                   — django-newsletter confirm / unsubscribe
    /anymail/mailgun/tracking/      — the Mailgun webhook

Prefer this over three separate includes. If you need different prefixes, include
`prblm_mailer.urls`, `newsletter.urls`, and `anymail.urls` yourself instead.
"""
from django.urls import include, path

urlpatterns = [
    path("mailer/", include("prblm_mailer.urls")),
    path("newsletter/", include("newsletter.urls")),
    path("anymail/", include("anymail.urls")),
]
