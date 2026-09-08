# Installing prblm-mailer into a Wagtail site — first run

A 10-minute walkthrough to install the plugin and see it working end to end, with
**nothing real sent**. For the full feature reference (delivery modes, forms/grouping,
tracking, CSV, going live) see `README.md`; this is just the quickest safe first run.

Works on **Wagtail 6 or 7 / Django 5.0–5.2**. Every change below goes in the **host site**,
never in the plugin.

---

## 1. Install

```bash
# from the host site's project root, with its virtualenv active
pip install -e /path/to/prblm-mailer
```

Pulls in `django-newsletter`, `django-anymail`, `mrml`, `sorl-thumbnail`.

## 2. Settings

```python
from prblm_mailer import with_required_apps

INSTALLED_APPS = with_required_apps(INSTALLED_APPS)   # adds newsletter, anymail, sorl.thumbnail, sites

SITE_ID = 1                                       # django-newsletter is per-site
WAGTAILADMIN_BASE_URL = "https://your-site.com"   # absolute URLs in emails

PRBLM_MAILER = {
    "NEWSLETTER_SLUG": "main",
    "FROM_EMAIL": "hello@example.com",
    "FROM_NAME": "Example",
    "BRAND_COLOR": "#2b6cb0",
    "DELIVERY": "dry_run",          # log only — nothing is sent. Change later (see §7 / README).
}
```

No Mailgun keys are needed while `DELIVERY` is `dry_run`, `console`, or `local`.
(For *why* each app/setting is needed, see the README — it explains them in full.)

## 3. URLs

One include mounts all the routes at their usual paths:

```python
from django.urls import include, path

urlpatterns = [
    # ...existing...
    path("", include("prblm_mailer.urls_bundle")),   # /mailer/, /newsletter/, /anymail/
]
```

## 4. Migrate, then create the list

```bash
python manage.py migrate

python manage.py shell -c "
from newsletter.models import Newsletter
Newsletter.objects.get_or_create(
    slug='main',
    defaults={'title': 'Main list', 'email': 'hello@example.com', 'sender': 'Example'},
)"
```

## 5. Look in the admin

Log into `/admin/`. You should see **Newsletters** and **Subscribers** in the left menu.

1. **Newsletters → Add.** Subject, a Content block, a Footer block (tick “show unsubscribe”).
   **Save & send.**
2. The **Send page**: a live preview on the right, **Send a test**, and **Who gets it**.
3. **Send a test** to yourself. With `DELIVERY="dry_run"` nothing is emailed — a line appears
   in the server log: `DRY_RUN: would send TEST of broadcast 1 to you@example.com`.

## 6. See the actual email (still nothing sent for real)

- **See it in the terminal:** set `PRBLM_MAILER["DELIVERY"] = "console"` and send a test — the
  full rendered email prints to the server log.
- **See it in a real inbox UI:** run a local mailbox and set `DELIVERY = "local"`:
  ```bash
  # needs Docker; add -d to run in the background
  docker run --rm -p 1080:1080 -p 1025:1025 marlonb/mailcrab:latest   # read at http://localhost:1080
  ```
  Send a test; it lands in mailcrab looking like a real email. (If the port isn’t up, the
  plugin tells you exactly this.)

To try a **full send** in dry-run, add a confirmed subscriber and use Who gets it → Proceed →
Send now:

```bash
python manage.py shell -c "
from newsletter.models import Newsletter, Subscription
nl = Newsletter.objects.get(slug='main')
Subscription.objects.get_or_create(newsletter=nl, email_field='test@example.com',
                                   defaults={'subscribed': True})"
```

---

## 7. When you’re ready to send for real

Follow **README §10 (Going live with Mailgun)**: set `EMAIL_BACKEND` + the `ANYMAIL` block
(EU vs US URL matters), set `PRBLM_MAILER["DELIVERY"] = "mailgun"`, point the Mailgun webhooks
at `/anymail/mailgun/tracking/`, and run `python manage.py mailgun_doctor` to check the setup.
Then send yourself a real test before the first real send.

## Next steps (all in README)

- **Signup forms & groups** — README §6–7 (`subscribe_from_form`, the abstract form bases).
- **Open/click tracking** — README §8, plus `mailgun_doctor` / `simulate_mailgun_click`.
- **CSV import/export** — README §9.

## If something’s off

- **No Newsletters/Subscribers menu** → `prblm_mailer` not in `INSTALLED_APPS`, or migrations
  not run.
- **Preview says “unavailable”** → a block failed to render; check the newsletter body.
- **Send errors about a reverse** → the three URL includes in §3 are missing.
- **Nothing in the log on a dry send** → `DELIVERY` isn’t a local mode, or logging isn’t
  showing INFO from `prblm_mailer`.
- **Migration won’t load on an older Wagtail** → regenerate the initial migration against your
  host’s Wagtail version (see README, “Cross-version note”).
