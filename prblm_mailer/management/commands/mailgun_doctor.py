"""Check every layer of the Mailgun click/open-tracking setup and say what's wrong.

Tracking spans several systems — Django, Mailgun, DNS and often a CDN/WAF in front
of your site — and a failure in any of them looks identical from the admin: no
clicks, no opens. This walks the whole chain in one go and reports which link is
broken.

    python manage.py mailgun_doctor

Read-only apart from one optional signed webhook post to our own URL (--probe),
which creates a throwaway EmailEvent and deletes it again.
"""
import base64
import hashlib
import hmac
import json
import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand

OK, BAD, WARN = "  ✓", "  ✗", "  !"


class Command(BaseCommand):
    help = "Diagnose the Mailgun click/open-tracking setup end to end."

    def add_arguments(self, parser):
        parser.add_argument(
            "--probe", action="store_true",
            help="Also POST a signed test event to our own public webhook URL.",
        )

    def handle(self, *args, **options):
        import requests

        self.failures = []
        anymail = getattr(settings, "ANYMAIL", {})
        api_key = anymail.get("MAILGUN_API_KEY", "")
        domain = anymail.get("MAILGUN_SENDER_DOMAIN", "")
        api_url = (anymail.get("MAILGUN_API_URL") or "https://api.mailgun.net/v3").rstrip("/")
        signing_key = anymail.get("MAILGUN_WEBHOOK_SIGNING_KEY", "") or api_key
        secret = anymail.get("WEBHOOK_SECRET", "")
        base_url = getattr(settings, "WAGTAILADMIN_BASE_URL", "").rstrip("/")
        auth = ("api", api_key)

        # --- 1. local configuration ---------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n1. Django configuration"))
        self._ok(bool(api_key), "Mailgun API key set")
        self._ok(bool(domain), f"sender domain set ({domain or '?'})")
        self._ok(
            bool(anymail.get("MAILGUN_WEBHOOK_SIGNING_KEY")),
            "webhook signing key set explicitly",
            "falling back to the API key — only correct on legacy accounts",
        )
        self._ok(bool(secret), "webhook basic-auth secret set")
        self._ok(bool(base_url), f"WAGTAILADMIN_BASE_URL set ({base_url or '?'})")
        self._ok("api.eu." in api_url, f"API region ({api_url})",
                   "if this account is EU, a US URL fails silently (and vice versa)")

        if not (api_key and domain):
            self.stdout.write(self.style.ERROR("\nCannot continue without an API key and domain."))
            return

        # --- 2. Mailgun domain settings -----------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Mailgun domain"))
        try:
            info = requests.get(f"{api_url}/domains/{domain}", auth=auth, timeout=20).json()
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"{BAD} cannot reach Mailgun: {exc}")
            return
        dom = info.get("domain", {})
        self._ok(dom.get("state") == "active", f"domain active ({dom.get('state')})")
        self._ok(dom.get("web_scheme") == "https",
                   f"tracking links use https (currently {dom.get('web_scheme')})",
                   "http links look untrustworthy in an email")
        cnames = [r for r in info.get("sending_dns_records", []) if r.get("record_type") == "CNAME"]
        for record in cnames:
            self._ok(record.get("valid") == "valid",
                       f"tracking CNAME {record.get('name')} verified in Mailgun",
                       "click Verify DNS in Mailgun; DNS may resolve before Mailgun rechecks")

        tracking = requests.get(f"{api_url}/domains/{domain}/tracking", auth=auth, timeout=20).json()
        click_on = tracking.get("tracking", {}).get("click", {}).get("active")
        open_on = tracking.get("tracking", {}).get("open", {}).get("active")
        self._ok(bool(click_on), "click tracking enabled")
        self._ok(bool(open_on), "open tracking enabled",
                   "opens won't be recorded until this is on")

        # --- 3. webhooks ---------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Registered webhooks"))
        hooks = requests.get(f"{api_url}/domains/{domain}/webhooks", auth=auth, timeout=20).json()
        hooks = hooks.get("webhooks", {})
        for event in ("clicked", "opened", "permanent_fail", "temporary_fail",
                      "complained", "unsubscribed"):
            urls = (hooks.get(event) or {}).get("urls") or []
            self._ok(bool(urls), f"{event} registered")
            for url in urls:
                if secret:
                    self._ok(f"//{secret}@" in url,
                               f"  {event} URL carries our basic-auth credentials",
                               "Mailgun will be rejected with 401")
                self._ok("/anymail/mailgun/tracking/" in url,
                           f"  {event} URL path correct")

        # --- 4. our endpoint, from the outside ------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. Our webhook endpoint"))
        hook_url = f"{base_url}/anymail/mailgun/tracking/"
        headers = {"Content-Type": "application/json",
                   # A bare python UA can get 403'd by a CDN/WAF browser check.
                   "User-Agent": "Mailgun/doctor"}
        if secret:
            headers["Authorization"] = "Basic " + base64.b64encode(secret.encode()).decode()

        try:
            unsigned = requests.post(hook_url, data="{}", headers=headers, timeout=20)
        except Exception as exc:  # noqa: BLE001
            self._ok(False, f"endpoint reachable at {hook_url}", str(exc)[:90])
            unsigned = None
        if unsigned is not None:
            self._ok(unsigned.status_code != 403, "endpoint not blocked by a CDN/WAF",
                     "add a WAF Skip rule for /anymail/ (e.g. Browser Integrity Check, Bot Fight Mode)")
            self._ok(unsigned.status_code in (400, 401),
                     f"endpoint reachable (unsigned request -> {unsigned.status_code})")

        if options["probe"] and unsigned is not None:
            ts, token = str(int(time.time())), uuid.uuid4().hex
            sig = hmac.new(signing_key.encode(), f"{ts}{token}".encode(), hashlib.sha256).hexdigest()
            payload = {
                "signature": {"timestamp": ts, "token": token, "signature": sig},
                "event-data": {"id": uuid.uuid4().hex, "event": "delivered",
                               "timestamp": float(ts),
                               "recipient": "mailgun-doctor@example.com",
                               "user-variables": {}},
            }
            signed = requests.post(hook_url, data=json.dumps(payload), headers=headers, timeout=20)
            self._ok(signed.status_code == 200,
                       f"signed event accepted ({signed.status_code})",
                       "400 = signing key mismatch, 401 = basic-auth mismatch")
            from prblm_mailer.models import EmailEvent
            EmailEvent.objects.filter(email="mailgun-doctor@example.com").delete()

        # --- 5. does Mailgun have clicks we never received? -----------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Clicks: Mailgun vs us"))
        events = requests.get(f"{api_url}/{domain}/events",
                              auth=auth, params={"event": "clicked", "limit": 25}, timeout=20).json()
        mailgun_clicks = events.get("items", [])
        from prblm_mailer.models import EngagementEvent
        ours = EngagementEvent.objects.filter(kind=EngagementEvent.KIND_CLICK).count()
        self.stdout.write(f"  Mailgun has recorded {len(mailgun_clicks)} recent click(s)")
        self.stdout.write(f"  we have stored       {ours} click(s)")

        if mailgun_clicks and ours == 0 and self.failures:
            self.stdout.write(self.style.ERROR(
                "\n  >> Mailgun IS recording clicks but none reach us.\n"
                "     The break is Mailgun -> our server: fix the failures above."))
        elif mailgun_clicks and ours == 0:
            # Config is sound, so these are almost certainly historical: Mailgun
            # gives up after its retry window and never backfills.
            self.stdout.write(self.style.WARNING(
                "\n  >> Configuration checks all pass, so these clicks are most likely\n"
                "     from BEFORE it was fixed — Mailgun does not replay events once\n"
                "     their retries are exhausted. Click a link in a real newsletter\n"
                "     now and re-run: a fresh click should appear within seconds."))
            for item in mailgun_clicks[:3]:
                uv = item.get("user-variables", {})
                self.stdout.write(f"     click on {item.get('url','?')[:60]} "
                                  f"| broadcast_id={uv.get('broadcast_id')} test={uv.get('test')}")
        elif not mailgun_clicks:
            self.stdout.write(
                "\n  >> Mailgun has no clicks recorded at all. Either nobody has clicked a\n"
                "     link in a REAL (non-test) newsletter yet, or the links aren't being\n"
                "     rewritten. Send a real one, click a link, and re-run this.")

        # --- verdict --------------------------------------------------------
        self.stdout.write("")
        if self.failures:
            self.stdout.write(self.style.ERROR(f"{len(self.failures)} problem(s):"))
            for line in self.failures:
                self.stdout.write(f"  - {line}")
        else:
            self.stdout.write(self.style.SUCCESS("All configuration checks passed."))

    def _ok(self, ok, label, hint=""):
        if ok:
            self.stdout.write(f"{OK} {label}")
        else:
            self.stdout.write(f"{BAD} {label}" + (f"  <- {hint}" if hint else ""))
            self.failures.append(label + (f" ({hint})" if hint else ""))
