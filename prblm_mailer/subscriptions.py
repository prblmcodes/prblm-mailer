"""Turn a form submission into a double-opt-in newsletter subscription.

The host site's form calls `subscribe_from_form` here, so the form records its
submission *and* adds the person to the mailing list with double opt-in.

Mirrors what django-newsletter's own subscribe view does: create a `Subscription`
in the unconfirmed state and send the activation email. `confirmed_subscriptions()`
(below) only returns confirmed, non-unsubscribed rows, so an unconfirmed address
never receives a broadcast.
"""
import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

# Which list the LS form feeds. The row is created by a data migration; the slug
# is overridable so another form could feed a different list later.
from .conf import get_setting

NEWSLETTER_SLUG = get_setting("NEWSLETTER_SLUG")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_default_newsletter():
    """The django-newsletter list the form subscribes to, or None if not set up.

    Keeps the list's sender identity in sync with settings. django-newsletter
    stores the activation email's From address on the Newsletter row itself, so a
    row seeded with a placeholder (or before .env was configured) would keep
    mailing From an unverified domain — Mailgun drops those and the confirmation
    never arrives. Reconciling here makes it self-healing: the From is always the
    Mailgun-verified address, with no manual admin step.
    """
    from newsletter.models import Newsletter

    newsletter = Newsletter.objects.filter(slug=NEWSLETTER_SLUG).first()
    if newsletter is not None:
        _sync_sender_identity(newsletter)
    return newsletter


def _sync_sender_identity(newsletter):
    """Point the list's From name/address at the configured (verified) sender."""
    from_email = get_setting("FROM_EMAIL")
    from_name = get_setting("FROM_NAME")

    changed = []
    if from_email and newsletter.email != from_email:
        newsletter.email = from_email
        changed.append("email")
    if from_name and newsletter.sender != from_name:
        newsletter.sender = from_name
        changed.append("sender")
    if changed:
        newsletter.save(update_fields=changed)
        logger.info("Synced newsletter sender identity from settings (%s)", ", ".join(changed))

    _ensure_linked_to_current_site(newsletter)


def _ensure_linked_to_current_site(newsletter):
    """Attach the list to the current Site if it isn't already.

    django-newsletter finds newsletters through a per-site manager (`on_site`), so
    a list not linked to the current Site is invisible to its confirm/unsubscribe
    views — every activation link 404s. The seed migration links it, but a Site
    whose domain is edited after deploy (or a list created another way) can end up
    unlinked. Reconciling here is self-healing, with no manual admin step.
    """
    from django.contrib.sites.models import Site

    site = Site.objects.get_current()
    if not newsletter.site.filter(pk=site.pk).exists():
        newsletter.site.add(site)
        logger.info("Linked newsletter %r to current site %s", newsletter.slug, site.domain)


def confirmed_subscriptions():
    """Everyone who may receive a broadcast: confirmed, not unsubscribed.

    The single source of truth for "who gets the newsletter". A broadcast never
    picks recipients — it sends to whatever this returns at send time, so the
    audience grows on its own as people confirm.
    """
    from newsletter.models import Subscription

    newsletter = get_default_newsletter()
    if newsletter is None:
        return Subscription.objects.none()
    return (
        Subscription.objects.filter(newsletter=newsletter, subscribed=True, unsubscribed=False)
        .select_related("user")
        .order_by("pk")
    )


def _find_email(cleaned_data):
    """The email address in a form submission.

    Prefers a field literally named ``email``; otherwise takes the first value
    that looks like an address. Keeps the glue working if the form's field names
    change, rather than hard-coding one key.
    """
    value = cleaned_data.get("email")
    if value and _EMAIL_RE.match(str(value).strip()):
        return str(value).strip()
    for v in cleaned_data.values():
        if isinstance(v, str) and _EMAIL_RE.match(v.strip()):
            return v.strip()
    return None


def _find_name(cleaned_data):
    for key in ("your_name", "name", "full_name"):
        v = cleaned_data.get(key)
        if v and _EMAIL_RE.match(str(v).strip()) is None:  # don't mistake email for name
            return str(v).strip()
    return ""


def _apply_groups(subscription, page, cleaned_data, groups):
    """Copy the submission's grouping answers onto the subscriber.

    Two sources, combined: answers to the page's grouping fields, and any groups
    the caller states outright (the newsletter signup block, which has no form
    fields of its own).

    Isolated in its own try/except: grouping is a convenience for targeting
    newsletters, so a problem here must never cost somebody their subscription or
    their opt-in email.
    """
    try:
        from .segments import apply_tags, tags_from_submission

        tags = tags_from_submission(page, cleaned_data) + list(groups or [])
        apply_tags(subscription, tags)
    except Exception:  # noqa: BLE001 — subscribing matters more than grouping
        logger.exception("Could not apply subscriber groups (subscription is unaffected)")


def subscribe_from_form(cleaned_data, page=None, groups=None):
    """Add the submitter to the newsletter list with double opt-in.

    `page` is the form page, used only to read which of its fields are marked as
    subscriber groups. `groups` is an explicit `[(group, answer), …]` for callers
    with no form fields to read. Both optional, so an existing caller that passes
    neither behaves exactly as before.

    Never raises — a newsletter hiccup must not break the visitor's form
    submission (they still get their landing page). Returns the Subscription, or
    None if there was nothing to do.
    """
    try:
        from newsletter.models import Subscription

        email = _find_email(cleaned_data)
        if not email:
            logger.warning("Newsletter signup: no email found in %s", list(cleaned_data))
            return None

        newsletter = get_default_newsletter()
        if newsletter is None:
            logger.error(
                "Newsletter signup: no list with slug %r — create one in the admin.",
                NEWSLETTER_SLUG,
            )
            return None

        name = _find_name(cleaned_data)
        subscription, created = Subscription.objects.get_or_create(
            newsletter=newsletter,
            email_field=email,
            defaults={"name_field": name},
        )

        # Already confirmed and active — do nothing, don't re-send the opt-in.
        # Groups are deliberately not updated here either: resubmitting the form
        # changes nothing for someone already on the list. Letting people change
        # their own preferences is a separate feature (a preference centre), not
        # something a stranger who knows your address should do by resubmitting.
        if subscription.subscribed and not subscription.unsubscribed:
            return subscription

        # New, or previously unsubscribed, or never confirmed → (re)start opt-in.
        #
        # The reset MUST go through .update(), not save(). django-newsletter's
        # Subscription.save() treats "unsubscribed True -> False" as consent and
        # immediately flips subscribed back to True — so a previously-unsubscribed
        # person would be silently re-added to the list without confirming, shown
        # "already subscribed", and emailed a pointless confirmation. .update()
        # writes the columns directly and skips that side effect, leaving them
        # genuinely pending until they click the confirmation link.
        if name and not subscription.name_field:
            Subscription.objects.filter(pk=subscription.pk).update(name_field=name)
        Subscription.objects.filter(pk=subscription.pk).update(
            subscribed=False, unsubscribed=False,
        )
        subscription.refresh_from_db()
        _apply_groups(subscription, page, cleaned_data, groups)
        # Route through the plugin's DELIVERY (not Django's EMAIL_BACKEND), so the
        # confirmation lands wherever broadcasts do — console/local inbox/Mailgun.
        from .sending import send_optin
        send_optin(subscription, "subscribe")
        logger.info("Newsletter opt-in email sent to %s (new=%s)", email, created)
        return subscription

    except Exception:  # noqa: BLE001 — the form submission must still succeed
        logger.exception("Newsletter signup failed (form submission itself is unaffected)")
        return None
