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
pip install "prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.2.0b1"
```

Pulls in `django-newsletter`, `django-anymail`, `mrml`, `sorl-thumbnail`.

Check the [releases page](https://github.com/prblmcodes/prblm-mailer/releases) for the
current tag, and pin it — `@main` moves under you between installs.

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

Working locally, add one more — in whichever settings file defines `DEBUG`, not in a base
file imported before it:

```python
NEWSLETTER_USE_HTTPS = False     # the dev server is http; https confirmation links won't open
```

No Mailgun keys are needed while `DELIVERY` is `dry_run`, `console`, or `local`.
(For *why* each app/setting is needed, see the README — it explains them in full.)

## 3. URLs

One include mounts all the routes at their usual paths:

```python
from django.urls import include, path
from wagtail import urls as wagtail_urls

urlpatterns = [
    # ...existing...
    path("", include("prblm_mailer.urls_bundle")),   # /mailer/, /newsletter/, /anymail/
    path("", include(wagtail_urls)),                 # Wagtail's catch-all stays LAST
]
```

**The order matters.** Wagtail's catch-all matches any path of plain word segments, so below
it every newsletter URL is swallowed. The symptom is memorable: the confirmation link in the
email works (it has an email address in it, which the catch-all doesn't match) and then the
page it redirects to 404s. `manage.py check` catches this as `prblm_mailer.W004`.

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

Then confirm the setup is sound:

```bash
python manage.py check
```

Clean output means you're ready. The checks name the five mistakes that otherwise fail
silently — missing `SITE_ID`, unset `WAGTAILADMIN_BASE_URL`, a Site row still set to
`example.com`, https links on an http site, and the URL-ordering trap above.

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

### Walk the signup flow

Worth doing once with `DELIVERY = "local"`, because it exercises the parts that depend on your
URLs and Site record — the ones that fail quietly if the setup is off:

1. Subscribe at `/newsletter/main/subscribe/`. You land on a **check your inbox** page.
2. The confirmation email appears in mailcrab, styled with your `BRAND_COLOR`.
3. Click its link. The confirm page shows the address and a button — **no activation code
   box** — plus *Deny subscription* for someone signed up by mistake.
4. Confirm → **“You’re all set!”**. Open the same link again and it says *already confirmed*
   rather than re-offering the form.
5. Check `/newsletter/main/unsubscribe/` too, and that the subscriber shows as **confirmed**
   under Subscribers (where you'll also find **Import CSV** / **Export CSV**, and no Edit
   button — the list isn't hand-edited).

If step 3 or 4 gives a 404, it's the URL ordering in §3. If the link points at `example.com`
or won't open over https, see §2 and the troubleshooting list below.

---

## 7. When you’re ready to send for real

Follow **README §11 (Going live with Mailgun)**: set `EMAIL_BACKEND` + the `ANYMAIL` block
(EU vs US URL matters), set `PRBLM_MAILER["DELIVERY"] = "mailgun"`, point the Mailgun webhooks
at `/anymail/mailgun/tracking/`, and run `python manage.py mailgun_doctor` to check the setup.
Then send yourself a real test before the first real send.

## Next steps (all in README)

- **Signup forms & groups** — README §6–7 (`subscribe_from_form`, the abstract form bases).
- **Conditional signup** — let a contact form offer the newsletter behind an opt-in
  checkbox: README §6b.
- **Open/click tracking** — README §8, plus `mailgun_doctor` / `simulate_mailgun_click`.
- **Styling the confirmation email and the public pages** — README §5 and §9.
- **CSV import/export**, from the Subscribers admin or the CLI — README §10.

## If something’s off

Run `python manage.py check` first — it names most of these outright.

- **No Newsletters/Subscribers menu** → `prblm_mailer` not in `INSTALLED_APPS`, or migrations
  not run.
- **Confirmation link 404s, or the page after it does** → the bundle is mounted below Wagtail's
  catch-all (§3). Check reports `W004`.
- **Confirmation link points at `example.com`** → the Site row is still Django's placeholder.
  Set `WAGTAILADMIN_BASE_URL` and the next signup corrects it; check reports `W002`.
- **Confirmation link is `https://localhost:8000/…` and won't open** → set
  `NEWSLETTER_USE_HTTPS = False` in your dev settings (§2). Check reports `W003`.
- **The signup form saves but nobody joins the list** → the page's “Collect newsletter
  subscribers” toggle is off, or its panel was never added to `content_panels`; or the form has
  an opt-in checkbox that the submitter left unticked (README §6b).
- **Clicking a link in mailcrab records no engagement** → expected. Tracking is Mailgun's, so
  it only works under `DELIVERY="mailgun"` (README §8).
- **Preview says “unavailable”** → a block failed to render; check the newsletter body.
- **Send errors about a reverse** → the three URL includes in §3 are missing.
- **Nothing in the log on a dry send** → `DELIVERY` isn’t a local mode, or logging isn’t
  showing INFO from `prblm_mailer`.
- **Migration won’t load on an older Wagtail** → regenerate the initial migration against your
  host’s Wagtail version (see README, “Cross-version note”).
