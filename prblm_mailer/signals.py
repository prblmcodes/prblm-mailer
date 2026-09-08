"""List hygiene + engagement, via Mailgun webhooks.

Keep mailing addresses that hard-bounce, or people who hit "spam", and Mailgun's
(and Gmail's) reputation systems notice. Anymail exposes Mailgun's webhooks as a
Django signal with signature verification built in; we listen for permanent
failures and complaints and unsubscribe those people automatically, and we record
clicks and opens as engagement.

Wire it up (host site):
  1. `path("anymail/", include("anymail.urls"))` in urls.py
  2. Mailgun → Webhooks: point permanent_fail, temporary_fail, complained,
     unsubscribed, clicked and opened at
     https://yoursite/anymail/mailgun/tracking/
  3. Set ANYMAIL["WEBHOOK_SECRET"] = "user:pass" and use the same in the webhook URL
  4. Enable click + open tracking on the Mailgun domain.
"""
import logging

from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from anymail.signals import tracking
from newsletter.models import Subscription

from .models import EmailEvent, EngagementEvent

logger = logging.getLogger(__name__)

# Events that mean "never email this person again".
HARD_EVENTS = {"bounced", "rejected", "complained", "unsubscribed"}


def _client_ip(event):
    """The event's IP, from Mailgun's raw payload.

    Anymail normalises the common fields but not this one, so it comes out of
    `esp_event`. Wrapped because the payload shape is Mailgun's to change, and a
    missing IP must never cost us the event.
    """
    try:
        return (event.esp_event or {}).get("event-data", {}).get("ip") or None
    except Exception:  # noqa: BLE001
        return None


def _dedupe_key(event, broadcast_id):
    """Mailgun's own event id — the only value stable across retries.

    NOT `event.event_id`: Anymail fills that from the webhook's signature *token*,
    which Mailgun regenerates for every delivery attempt. Using it would mean a
    fresh key on each retry, so the retries this key exists to collapse would each
    create their own row.
    """
    try:
        event_id = (event.esp_event or {}).get("event-data", {}).get("id")
    except Exception:  # noqa: BLE001
        event_id = None
    if event_id:
        return str(event_id)
    # Last resort for a payload without one — better than no dedupe at all.
    return f"{broadcast_id}:{event.recipient}:{event.timestamp}"


def _record_engagement(event, broadcast_id, kind):
    """Store a click or open. Never raises — see handle_mailgun_event."""
    metadata = event.metadata or {}

    if metadata.get("test"):
        # From the "send a test to yourself" copy — no real subscriber, so counting
        # it would inflate the newsletter's stats.
        logger.info("Ignored a %s from a test send of broadcast %s", kind, broadcast_id)
        return

    if not broadcast_id:
        # broadcast is non-nullable: without it there is nothing to attribute to.
        logger.warning(
            "%s from %s could not be attributed to a broadcast — ignoring",
            kind, event.recipient,
        )
        return

    # Prefer the primary key we attached at send time; it survives a case change or
    # a resubscribe. Fall back to the address only if it's missing (e.g. an email
    # sent before tracking went live).
    subscription = None
    subscription_id = metadata.get("subscription_id")
    if subscription_id:
        subscription = Subscription.objects.filter(pk=subscription_id).first()
    if subscription is None and event.recipient:
        subscription = Subscription.objects.filter(
            email_field__iexact=event.recipient
        ).first()
    if subscription is None:
        logger.warning(
            "%s from %s has no resolvable subscriber — recording it unattributed",
            kind, event.recipient,
        )

    url = ""
    if kind == EngagementEvent.KIND_CLICK:
        url = (event.click_url or "")[:2000]

    EngagementEvent.objects.get_or_create(
        mailgun_event_id=_dedupe_key(event, broadcast_id),
        defaults={
            "kind": kind,
            "broadcast_id": broadcast_id,
            "subscription": subscription,
            "url": url,
            "at": event.timestamp or timezone.now(),
            "ip_address": _client_ip(event),
            "user_agent": event.user_agent or "",
        },
    )


@receiver(tracking)
def handle_mailgun_event(sender, event, esp_name, **kwargs):
    from .models import Broadcast

    # Link the broadcast only if it still exists — webhooks arrive late and can
    # reference one since deleted; a dangling FK would crash the webhook.
    broadcast_id = (event.metadata or {}).get("broadcast_id")
    if broadcast_id and not Broadcast.objects.filter(pk=broadcast_id).exists():
        broadcast_id = None

    kinds = {"clicked": EngagementEvent.KIND_CLICK, "opened": EngagementEvent.KIND_OPEN}
    if event.event_type in kinds:
        # Engagement is isolated: analytics must never break the path that keeps the
        # list clean (bounces/complaints below).
        try:
            _record_engagement(event, broadcast_id, kinds[event.event_type])
        except Exception:  # noqa: BLE001
            logger.exception("Could not record a %s (the webhook is unaffected)", event.event_type)
        return

    EmailEvent.objects.create(
        email=event.recipient,
        event=event.event_type,
        reason=event.description or getattr(event, "reject_reason", "") or "",
        broadcast_id=broadcast_id,
    )

    if event.event_type not in HARD_EVENTS:
        # Soft bounces (full mailbox, greylisting) — Mailgun retries these itself.
        return

    # iexact, not exact: Mailgun doesn't always report the address in the case the
    # subscriber typed. An exact match would silently fail to unsubscribe them, so
    # we'd keep mailing an address that has already hard-bounced.
    updated = Subscription.objects.filter(
        email_field__iexact=event.recipient, unsubscribed=False
    ).update(
        subscribed=False,
        unsubscribed=True,
        unsubscribe_date=timezone.now(),
    )
    if updated:
        logger.info("Unsubscribed %s after %s event from %s",
                    event.recipient, event.event_type, esp_name)


@receiver(pre_delete, sender=Subscription)
def scrub_engagement_ips_on_delete(sender, instance, **kwargs):
    """Blank the IP on a deleted subscriber's engagement rows.

    `EngagementEvent.subscription` is SET_NULL so a sent newsletter's totals stay
    accurate after someone is removed. But an IP on its own can still identify a
    person, so unlinking alone wouldn't be a real erasure. Must run on **pre**_delete:
    once SET_NULL has fired, the foreign key is gone and their rows can't be found.
    """
    scrubbed = EngagementEvent.objects.filter(subscription=instance).update(ip_address=None)
    if scrubbed:
        logger.info("Scrubbed the IP from %s engagement row(s) for a deleted subscriber", scrubbed)
