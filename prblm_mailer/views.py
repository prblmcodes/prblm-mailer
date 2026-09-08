"""Public views: RFC 8058 one-click unsubscribe, and deny-a-pending-signup.

The one-click token is a signed subscription id — unguessable, so no CSRF/login is
needed (and the mail provider can't supply either). Only POST unsubscribes; a GET
shows a confirm button, because scanners and prefetchers fetch header URLs and must
not be able to remove somebody who never asked to leave. Tokens expire (see tokens.py).

The Wagtail admin send/preview views live in admin.py (added with the admin phase).
"""
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .tokens import ONECLICK_MAX_AGE, SALT

_PAGE = (
    "<!doctype html><meta charset='utf-8'>"
    "<div style='font-family:system-ui;max-width:32em;margin:4em auto;text-align:center'>{}</div>"
)


def _unsubscribe(pk):
    from newsletter.models import Subscription

    return Subscription.objects.filter(pk=pk, unsubscribed=False).update(
        subscribed=False,
        unsubscribed=True,
        unsubscribe_date=timezone.now(),
    )


@csrf_exempt  # the mail provider POSTs cross-origin with no CSRF token; the signed token is the auth
def oneclick_unsubscribe(request, token):
    """RFC 8058 one-click unsubscribe. POST unsubscribes; GET shows a confirm button."""
    try:
        pk = signing.loads(token, salt=SALT, max_age=ONECLICK_MAX_AGE)
    except signing.SignatureExpired:
        return HttpResponse(_PAGE.format(
            "<p>This unsubscribe link has expired.</p>"
            "<p>You can unsubscribe from the link in any more recent email, "
            "or reply and ask us to remove you.</p>"
        ), status=400)
    except signing.BadSignature:
        return HttpResponse(_PAGE.format(
            "<p>This unsubscribe link is invalid.</p>"), status=400)

    if request.method != "POST":
        return HttpResponse(_PAGE.format(
            "<p>Unsubscribe from this newsletter?</p>"
            f"<form method='post' action='{request.path}'>"
            "<button type='submit' style='font:inherit;padding:.6em 1.4em;cursor:pointer'>"
            "Yes, unsubscribe me</button></form>"
        ))

    _unsubscribe(pk)
    if request.headers.get("accept", "").startswith("text/html"):
        return HttpResponse(_PAGE.format(
            "<p>You have been unsubscribed. "
            "You won&rsquo;t receive any more of these emails.</p>"))
    # RFC 8058 one-click: the provider just needs a 200, no body.
    return HttpResponse(status=200)


def deny_subscription(request):
    """Decline a pending signup and invalidate its confirmation link.

    Deletes the still-unconfirmed Subscription (so its activation link 404s
    afterwards). Auth is the activation code in the link; only a NOT-yet-confirmed
    subscription can be removed, so this can never drop an active subscriber.
    """
    from newsletter.models import Subscription

    if request.method != "POST":
        return redirect("/")

    email = (request.POST.get("email") or "").strip()
    code = (request.POST.get("code") or "").strip()
    if email and code:
        Subscription.objects.filter(
            email_field__iexact=email, activation_code=code, subscribed=False
        ).delete()
    return render(request, "prblm_mailer/subscription_denied.html")
