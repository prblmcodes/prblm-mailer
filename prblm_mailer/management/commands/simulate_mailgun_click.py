"""Replay a realistic Mailgun `clicked` webhook against this site, locally.

Click tracking needs Mailgun to reach us over the internet, so the only part of
the chain you can't try on a laptop is Mailgun itself. This fakes that one step:
it builds the JSON payload Mailgun actually posts — signature block, `event-data`,
`user-variables`, `client-info` — signs it properly, and sends it through the real
webhook URL.

Everything downstream is the genuine article: Anymail's signature check, Anymail's
Mailgun payload parser, our signal handler, the EngagementEvent row, the stats panel.

    python manage.py simulate_mailgun_click                    # newest sent newsletter
    python manage.py simulate_mailgun_click --broadcast 12
    python manage.py simulate_mailgun_click --url https://example.com/thing

Worth running before trusting the live setup: the unit tests build Anymail's
*normalised* event object directly, so they never exercise Mailgun's real payload
shape. This does.
"""
import hashlib
import hmac
import json
import time
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.test.utils import override_settings

# Local-only stand-ins, so this works whatever is (or isn't) in your .env.
DEV_SIGNING_KEY = "local-signing-key"
DEV_BASIC_AUTH = "local:secret"

WEBHOOK_PATH = "/anymail/mailgun/tracking/"


class Command(BaseCommand):
    help = "Post a fake but realistic Mailgun 'clicked' webhook to this site."

    def add_arguments(self, parser):
        parser.add_argument("--broadcast", type=int, help="Broadcast pk (default: newest sent)")
        parser.add_argument("--subscriber", type=int, help="Subscription pk (default: first recipient)")
        parser.add_argument("--url", default="https://example.com/a-link", help="The link that was clicked")
        parser.add_argument("--ip", default="203.0.113.42")
        parser.add_argument(
            "--event-id",
            help="Reuse a specific Mailgun event id — pass the same one twice to "
                 "prove retries are deduplicated.",
        )
        parser.add_argument(
            "--unknown-subscriber", action="store_true",
            help="Omit subscription_id, to test the email-address fallback.",
        )

    def handle(self, *args, **options):
        from prblm_mailer.models import Broadcast, EngagementEvent
        from prblm_mailer.audience import resolve

        broadcast = self._get_broadcast(Broadcast, options["broadcast"])
        subscription = self._get_subscription(resolve, broadcast, options["subscriber"])

        user_variables = {"broadcast_id": str(broadcast.pk)}
        if not options["unknown_subscriber"]:
            user_variables["subscription_id"] = str(subscription.pk)

        payload = self._payload(
            recipient=subscription.email, url=options["url"],
            ip=options["ip"], user_variables=user_variables,
            event_id=options["event_id"],
        )

        clicks = EngagementEvent.objects.filter(
            broadcast=broadcast, kind=EngagementEvent.KIND_CLICK)
        before = clicks.count()
        response = self._post(payload)

        self.stdout.write(f"Webhook responded {response.status_code}")
        if response.status_code != 200:
            raise CommandError(
                f"Rejected: {response.content[:300].decode(errors='replace')}"
            )

        after = clicks.count()
        if after == before:
            if options["event_id"]:
                self.stdout.write(self.style.SUCCESS(
                    f"Accepted and deduplicated — event {options['event_id']} was already "
                    f"recorded, so no second row was created. This is what happens every "
                    f"time Mailgun retries."
                ))
                return
            raise CommandError(
                "Webhook accepted the payload but no EngagementEvent was created — "
                "check the handler's log output."
            )

        click = clicks.first()
        self.stdout.write(self.style.SUCCESS("Click recorded:"))
        self.stdout.write(f"  url          {click.url}")
        self.stdout.write(f"  subscriber   {click.subscription or 'unattributed'}")
        self.stdout.write(f"  ip           {click.ip_address}")
        self.stdout.write(f"  user agent   {click.user_agent[:60]}")

        stats = broadcast.engagement_stats()
        self.stdout.write(
            f"\n{broadcast.subject!r}: {stats['clicks_total']} click(s), "
            f"{stats['clicks_unique']} subscriber(s)"
            + (f", {stats['click_rate']}% of {broadcast.emails_sent} sent"
               if stats["click_rate"] is not None else "")
        )
        self.stdout.write(
            "To prove retries are deduplicated, run it again with "
            "--event-id=<anything> twice."
        )

    # --- helpers ---------------------------------------------------------

    def _get_broadcast(self, Broadcast, pk):
        if pk:
            broadcast = Broadcast.objects.filter(pk=pk).first()
            if broadcast is None:
                raise CommandError(f"No newsletter with pk {pk}.")
            return broadcast
        broadcast = Broadcast.objects.filter(status=Broadcast.STATUS_SENT).first()
        if broadcast is None:
            raise CommandError(
                "No sent newsletter to attach a click to. Send one first, or pass --broadcast."
            )
        return broadcast

    def _get_subscription(self, resolve, broadcast, pk):
        from newsletter.models import Subscription

        if pk:
            subscription = Subscription.objects.filter(pk=pk).first()
            if subscription is None:
                raise CommandError(f"No subscriber with pk {pk}.")
            return subscription
        subscription = resolve(broadcast).first()
        if subscription is None:
            raise CommandError("That newsletter has no resolvable recipients.")
        return subscription

    def _payload(self, *, recipient, url, ip, user_variables, event_id=None):
        """The shape Mailgun really posts for a click."""
        timestamp = str(int(time.time()))
        token = uuid.uuid4().hex
        signature = hmac.new(
            key=DEV_SIGNING_KEY.encode("ascii"),
            msg=f"{timestamp}{token}".encode("ascii"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return {
            "signature": {"timestamp": timestamp, "token": token, "signature": signature},
            "event-data": {
                "id": event_id or uuid.uuid4().hex,   # dedupe key
                "event": "clicked",
                "timestamp": float(timestamp),
                "recipient": recipient,
                "url": url,
                "ip": ip,
                "client-info": {
                    "client-name": "Chrome",
                    "client-type": "browser",
                    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0",
                },
                "user-variables": user_variables,
                "message": {"headers": {"message-id": f"{uuid.uuid4().hex}@example.com"}},
            },
        }

    def _post(self, payload):
        import base64

        auth = base64.b64encode(DEV_BASIC_AUTH.encode()).decode()
        # Override the keys so this works on any machine, with or without a .env —
        # the code path being exercised is identical either way.
        with override_settings(
            ANYMAIL={
                "MAILGUN_API_KEY": DEV_SIGNING_KEY,
                "MAILGUN_WEBHOOK_SIGNING_KEY": DEV_SIGNING_KEY,
                "WEBHOOK_SECRET": DEV_BASIC_AUTH,
            }
        ):
            return Client().post(
                WEBHOOK_PATH,
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Basic {auth}",
            )
