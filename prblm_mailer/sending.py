"""Render a broadcast to email HTML and send it via Mailgun (anymail).

The body (MJML blocks) compiles to email-safe HTML with `mrml`. Sending goes through
Anymail's Mailgun backend using the batch API: one call per 1000 recipients, with
per-recipient merge variables, so nobody sees another address and each person gets
their own unsubscribe link.

`DRY_RUN` (a package setting, defaults to DEBUG) logs the message instead of posting
it — the one safety valve dev and staging need.
"""
import logging
import socket

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags

from anymail.message import AnymailMessage

from . import audience
from .conf import DELIVERY_MODES, get_setting
from .models import Broadcast
from .tokens import oneclick_token

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000  # Mailgun's per-batch recipient limit

# The merge variables that appear in the HTML/headers as %recipient.KEY%. Mailgun
# substitutes these per recipient at send time; the local modes do it in Python
# (see _personalize) since only Mailgun understands the placeholder syntax.
PLACEHOLDER_KEYS = ("name", "email", "unsubscribe_url", "oneclick_url")


def _base_url():
    """The site's absolute base URL for email links.

    Prefers WAGTAILADMIN_BASE_URL; falls back to the current Wagtail Site's root URL
    so links still resolve when it isn't set (a startup check warns about this).
    """
    base = getattr(settings, "WAGTAILADMIN_BASE_URL", "") or ""
    if base:
        return base.rstrip("/")
    try:
        from wagtail.models import Site

        site = Site.objects.filter(is_default_site=True).first() or Site.objects.first()
        if site is not None:
            return site.root_url.rstrip("/")
    except Exception:  # noqa: BLE001 — never let URL-building crash a send
        pass
    return ""


def absolute_url(path):
    return f"{_base_url()}{path}"


def _from_email():
    """"Name <addr>" if a from-name is configured, else the bare address."""
    addr = get_setting("FROM_EMAIL")
    name = get_setting("FROM_NAME")
    return f'"{name}" <{addr}>' if name else addr


def render_email_html(broadcast):
    """The broadcast's body, as email-ready HTML (MJML compiled by mrml)."""
    import mrml

    # The footer (company name, postal address, contact) is authored per-newsletter
    # in the Footer block — there is no fixed template footer to fill from settings.
    mjml = render_to_string("prblm_mailer/email.html", {"broadcast": broadcast})
    return mrml.to_html(mjml).content


def subscription_context(subscription):
    """Per-recipient merge variables, substituted by Mailgun at send time."""
    return {
        "name": subscription.name or "",
        "email": subscription.email,
        # Visible link in the body — django-newsletter's confirm-flow URL.
        "unsubscribe_url": absolute_url(subscription.unsubscribe_activate_url()),
        # One-click target for the List-Unsubscribe header (RFC 8058).
        "oneclick_url": absolute_url(
            reverse("prblm_mailer:oneclick_unsubscribe", args=[oneclick_token(subscription)])
        ),
    }


def _delivery():
    """The active delivery mode, validated."""
    mode = get_setting("DELIVERY")
    if mode not in DELIVERY_MODES:
        raise ImproperlyConfigured(
            f"PRBLM_MAILER['DELIVERY'] must be one of {DELIVERY_MODES}, got {mode!r}."
        )
    return mode


def delivery_mode():
    """The active, validated delivery mode — public helper for the admin UI."""
    return _delivery()


def _personalize(html, context):
    """Substitute the %recipient.KEY% placeholders ourselves (what Mailgun would do).

    Used by the console/local modes and by test sends, where there is no Mailgun to
    expand the placeholders — otherwise the email shows raw %recipient.…% text.
    """
    for key in PLACEHOLDER_KEYS:
        html = html.replace(f"%recipient.{key}%", str(context.get(key, "")))
    return html


def _check_smtp_reachable(host, port):
    """Fail with a helpful hint if no local inbox is listening (DELIVERY='local')."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return
    except OSError as exc:
        raise RuntimeError(
            f"DELIVERY='local' but nothing is listening on {host}:{port}. Start a local "
            f"inbox first — e.g. mailcrab:\n"
            f"    docker run -d -p 1080:1080 -p 1025:1025 marlonb/mailcrab\n"
            f"then read the mail at http://localhost:1080  ({exc})"
        ) from exc


def _local_connection(mode):
    """A mail connection for a local mode: the console, or SMTP to a local inbox."""
    if mode == "console":
        return get_connection("django.core.mail.backends.console.EmailBackend")
    host = get_setting("LOCAL_SMTP_HOST")
    port = int(get_setting("LOCAL_SMTP_PORT"))
    _check_smtp_reachable(host, port)
    return get_connection(
        "django.core.mail.backends.smtp.EmailBackend", host=host, port=port,
    )


def _send_local(broadcast, html, subscriptions, connection):
    """Send one personalized copy per recipient through `connection` (console/SMTP).

    No Mailgun batch/merge — each recipient gets their own message with the merge
    placeholders already filled in, so a local inbox shows a real, finished email.
    Returns (sent, failed); a single bad recipient is logged and skipped, not fatal.
    """
    reply_to = get_setting("REPLY_TO")
    sent = failed = 0
    for subscription in subscriptions:
        context = subscription_context(subscription)
        personal_html = _personalize(html, context)
        message = EmailMultiAlternatives(
            subject=broadcast.subject,
            body=strip_tags(personal_html),
            from_email=_from_email(),
            to=[subscription.email],
            connection=connection,
        )
        message.attach_alternative(personal_html, "text/html")
        message.extra_headers = {
            "List-Unsubscribe": f"<{context['oneclick_url']}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
        if reply_to:
            message.reply_to = [reply_to]
        try:
            message.send()
            sent += 1
        except Exception:  # noqa: BLE001 — one bad address must not stop the run
            failed += 1
            logger.exception("Local delivery to %s failed", subscription.email)
    return sent, failed


def _send_mailgun(broadcast, html, subscriptions):
    """Send via Anymail's Mailgun batch API. Returns (sent, failed)."""
    sent = failed = 0
    connection = get_connection()
    for i in range(0, len(subscriptions), BATCH_SIZE):
        batch = subscriptions[i : i + BATCH_SIZE]
        message = _build_message(
            subject=broadcast.subject, html=html, subscriptions=batch,
            connection=connection, broadcast=broadcast,
        )
        message.send()
        recipients = message.anymail_status.recipients
        sent += len(recipients)
        failed += sum(1 for r in recipients.values() if r.status in ("failed", "rejected"))
    return sent, failed


def _build_message(*, subject, html, subscriptions, connection=None, broadcast=None):
    """One AnymailMessage covering a batch of up to BATCH_SIZE recipients."""
    merge_data = {s.email: subscription_context(s) for s in subscriptions}

    message = AnymailMessage(
        subject=subject,
        body=strip_tags(html),  # plain-text fallback
        from_email=_from_email(),
        to=list(merge_data.keys()),
        connection=connection,
    )
    message.attach_alternative(html, "text/html")
    message.merge_data = merge_data
    message.merge_global_data = {"name": "", "unsubscribe_url": "", "oneclick_url": ""}

    # Per-recipient id, so a future click/event webhook can attribute correctly. Must
    # be merge_metadata, not metadata: a plain custom variable would apply to the whole
    # batch and pin every event to one person.
    message.merge_metadata = {
        s.email: {"subscription_id": str(s.pk)} for s in subscriptions
    }
    if broadcast is not None:
        message.metadata = {"broadcast_id": str(broadcast.pk)}
        message.tags = [f"broadcast-{broadcast.pk}"]

    # RFC 8058 one-click unsubscribe — required by Gmail/Yahoo for bulk since 2024.
    message.extra_headers = {
        "List-Unsubscribe": "<%recipient.oneclick_url%>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    reply_to = get_setting("REPLY_TO")
    if reply_to:
        message.reply_to = [reply_to]
    return message


def send_test(broadcast, email):
    """Send one test copy to `email`. Merge tags get dummy values so they render."""
    html = render_email_html(broadcast)
    mode = _delivery()

    if mode == "dry_run":
        logger.info("DRY_RUN: would send TEST of broadcast %s to %s (%d bytes HTML)",
                    broadcast.pk, email, len(html))
        return

    if mode in ("console", "local"):
        # No Mailgun to expand placeholders — fill dummies in ourselves.
        personal_html = _personalize(
            html, {"name": "there", "email": email, "unsubscribe_url": "#", "oneclick_url": "#"})
        message = EmailMultiAlternatives(
            subject=f"[TEST] {broadcast.subject}",
            body=strip_tags(personal_html),
            from_email=_from_email(),
            to=[email],
            connection=_local_connection(mode),
        )
        message.attach_alternative(personal_html, "text/html")
        message.send()
        return

    message = AnymailMessage(
        subject=f"[TEST] {broadcast.subject}",
        body=strip_tags(html),
        from_email=_from_email(),
        to=[email],
    )
    message.attach_alternative(html, "text/html")
    message.merge_global_data = {
        "name": "there", "unsubscribe_url": "#", "oneclick_url": "#",
    }
    message.metadata = {"broadcast_id": str(broadcast.pk), "test": "1"}
    message.send()


def send_optin(subscription, action="subscribe"):
    """Send django-newsletter's opt-in/confirmation email via the plugin's DELIVERY.

    django-newsletter would send it through Django's EMAIL_BACKEND, ignoring our
    delivery mode — so a dev with DELIVERY="local" still wouldn't see it in mailcrab.
    We reuse its templates and activation URL (so the confirm link is identical) but
    route the send the same way broadcasts go: logged under dry_run, printed under
    console, to the local inbox under local, via Mailgun under mailgun.
    """
    from django.contrib.sites.models import Site
    from newsletter.models import get_render_context

    newsletter = subscription.newsletter
    subject_t, text_t, html_t = newsletter.get_templates(action)
    context = get_render_context(
        date=subscription.subscribe_date,
        site=Site.objects.get_current(),
        newsletter=newsletter,
        subscription=subscription,
    )
    subject = subject_t.render(context).strip()
    text = text_t.render(context)
    html = html_t.render(context) if html_t else None

    mode = _delivery()
    if mode == "dry_run":
        logger.info("DRY_RUN: would send opt-in (%s) to %s", action, subscription.email)
        return

    connection = _local_connection(mode) if mode in ("console", "local") else None
    message = EmailMultiAlternatives(
        subject, text, from_email=newsletter.get_sender(),
        to=[subscription.email], connection=connection,
    )
    if html:
        message.attach_alternative(html, "text/html")
    message.send()


def send_broadcast(broadcast_id):
    """Send a broadcast to every confirmed subscriber."""
    broadcast = Broadcast.objects.get(pk=broadcast_id)

    if broadcast.status in (Broadcast.STATUS_SENDING, Broadcast.STATUS_SENT):
        logger.warning("Broadcast %s is already %s — refusing to send twice",
                       broadcast_id, broadcast.status)
        return

    broadcast.status = Broadcast.STATUS_SENDING
    broadcast.save(update_fields=["status", "updated_at"])

    html = render_email_html(broadcast)
    subscriptions = list(audience.resolve(broadcast))
    mode = _delivery()
    sent = failed = 0

    try:
        if mode == "dry_run":
            for i in range(0, len(subscriptions), BATCH_SIZE):
                batch = subscriptions[i : i + BATCH_SIZE]
                logger.info("DRY_RUN: would send broadcast %s to %d recipient(s): %s",
                            broadcast_id, len(batch), [s.email for s in batch])
                sent += len(batch)
        elif mode in ("console", "local"):
            sent, failed = _send_local(
                broadcast, html, subscriptions, _local_connection(mode))
        else:
            sent, failed = _send_mailgun(broadcast, html, subscriptions)
    except Exception as exc:  # noqa: BLE001 — record the reason rather than swallow it
        broadcast.status = Broadcast.STATUS_FAILED
        broadcast.error = str(exc)
        broadcast.save(update_fields=["status", "error", "updated_at"])
        logger.exception("Broadcast %s failed", broadcast_id)
        raise

    broadcast.mark_sent(html=html, sent=sent - failed, failed=failed)
    logger.info("Broadcast %s sent to %s recipient(s) (%s failed) [%s]",
                broadcast_id, sent - failed, failed, mode)
