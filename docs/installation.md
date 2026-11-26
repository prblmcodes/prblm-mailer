# Installation

This guide installs prblm-mailer into an existing Wagtail site and walks you through a first
run with **nothing sent for real**. Every change goes in your site, never in the plugin.

Requirements: Wagtail 6, 7 or 8 · Django 5.0–6.1 · Python 3.12+.

- [1. Install the package](#1-install-the-package)
- [2. Settings](#2-settings)
- [3. URLs](#3-urls)
- [4. Migrate and create the mailing list](#4-migrate-and-create-the-mailing-list)
- [5. First run](#5-first-run)
- [6. Walk the signup flow](#6-walk-the-signup-flow)
- [7. Next steps](#7-next-steps)
- [Troubleshooting](#troubleshooting)

---

## 1. Install the package

From your site's project root, with its virtualenv active:

```bash
pip install "prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.6.0b1"
```

Or add the same line to your `requirements.txt`:

```
prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.6.0b1
```

Each [release](https://github.com/prblmcodes/prblm-mailer/releases) also has a wheel attached,
which installs without git:

```bash
pip install https://github.com/prblmcodes/prblm-mailer/releases/download/v0.6.0b1/prblm_mailer-0.6.0b1-py3-none-any.whl
```

**Pin a tag, not `main`.** Tags never change, so every rebuild installs identical code;
`main` moves between installs.

This pulls in `django-newsletter`, `django-anymail`, `mrml` and `sorl-thumbnail`.

## 2. Settings

```python
from prblm_mailer import with_required_apps

INSTALLED_APPS = with_required_apps(INSTALLED_APPS)

SITE_ID = 1
WAGTAILADMIN_BASE_URL = "https://your-site.com"

PRBLM_MAILER = {
    "NEWSLETTER_SLUG": "main",          # the list you create in step 4
    "FROM_EMAIL": "hello@example.com",
    "FROM_NAME": "Example",
    "BRAND_COLOR": "#2b6cb0",           # buttons, the confirmation email, public pages
    "DELIVERY": "dry_run",              # dry_run | console | local | mailgun
}
```

In your **local development** settings (the file that sets `DEBUG`), add:

```python
WAGTAILADMIN_BASE_URL = "http://localhost:8000"   # exactly how you open the dev server
NEWSLETTER_USE_HTTPS = False                      # the dev server is http
```

No Mailgun keys are needed until `DELIVERY` is `"mailgun"`. Every `PRBLM_MAILER` key is listed
in the [configuration reference](configuration.md#prblm_mailer-settings).

### What `with_required_apps` adds, and why

It appends the apps prblm-mailer needs, skipping any you already list:

| App | Why it's needed |
|---|---|
| `prblm_mailer` | The plugin: Newsletters and Subscribers admin, sending, tracking. |
| `newsletter` | **django-newsletter** — the mailing list, subscribers and double opt-in. |
| `sorl.thumbnail` | An image dependency of django-newsletter. |
| `anymail` | Sends through Mailgun and receives its webhooks (bounces, opens, clicks). |
| `django.contrib.sites` | django-newsletter is built on Django's sites framework (see `SITE_ID`). |

It also puts `prblm_mailer` **before** `newsletter`, so the plugin's styled pages replace
django-newsletter's plain ones. If you list the apps by hand, keep that order.

> Why can't it be one app that hides the rest? Django reads `INSTALLED_APPS` once at startup,
> so an app can't register other apps for you. These are separate apps with their own models
> and migrations — `with_required_apps` just turns five lines into one.

### Why `SITE_ID`

django-newsletter attaches each list to a Django `Site`, and its confirm/unsubscribe views look
up "the current site" through `SITE_ID`. Without it those pages 404. You don't need multiple
sites — `SITE_ID = 1` is all it wants. `manage.py check` errors (`E001`) if it's missing.

### Why `WAGTAILADMIN_BASE_URL`

Emails are opened in Gmail or Outlook, far from your server, so every link and image in them
must be an **absolute** URL. This setting is the base for unsubscribe links, image addresses
and social icons.

- **Locally:** exactly the address you open the dev server at — `http://localhost:8000` and
  `http://127.0.0.1:8000` count as different hosts.
- **In production:** `https://your-real-domain.com`.

If it's unset, the plugin falls back to your Wagtail Site's URL and `manage.py check` warns
(`W001`). Set it explicitly before any real send.

## 3. URLs

One include mounts everything at its usual path:

```python
from django.urls import include, path
from wagtail import urls as wagtail_urls

urlpatterns = [
    # ...your other URLs...
    path("", include("prblm_mailer.urls_bundle")),   # /mailer/, /newsletter/, /anymail/
    path("", include(wagtail_urls)),                 # Wagtail's catch-all stays LAST
]
```

> **Order matters.** Wagtail's page pattern matches any path made of plain words, so if the
> bundle sits below it every newsletter URL is swallowed. The symptom is confusing: the link
> in the confirmation email *works* (it contains an email address, which the catch-all doesn't
> match) and then the "subscription activated" page it redirects to 404s.
> `manage.py check` detects this (`W004`) and names whatever is answering instead.

The routes it mounts are listed in the [configuration reference](configuration.md#urls). To use
different prefixes, include `prblm_mailer.urls`, `newsletter.urls` and `anymail.urls` yourself.

## 4. Migrate and create the mailing list

```bash
python manage.py migrate

python manage.py shell -c "
from newsletter.models import Newsletter
Newsletter.objects.get_or_create(
    slug='main',
    defaults={'title': 'Main list', 'email': 'hello@example.com', 'sender': 'Example'},
)"

python manage.py check
```

That `Newsletter` row **is** your mailing list; its slug must match
`PRBLM_MAILER["NEWSLETTER_SLUG"]` (`"main"` unless you changed it).
[Managing subscribers](subscribers.md#the-list-and-groups) explains how it relates to groups.

A clean `check` means you're ready. It reports the setup mistakes that otherwise fail
silently — see [startup checks](configuration.md#startup-checks).

## 5. First run

Log into `/admin/`. You'll see **Newsletters** and **Subscribers** in the menu.

1. **Newsletters → Add.** Enter a subject, add a **Content** block and a **Footer** block (tick
   *show unsubscribe*), and press **Save & send**.
2. The **Send page** opens: a live preview, **Send a test**, and **Who gets it**.
3. **Send a test** to your own address.

What happens depends on `DELIVERY`:

| `DELIVERY` | Where the test goes |
|---|---|
| `dry_run` | Nowhere. The admin says "Dry run — nothing was actually emailed", and one line is logged at INFO level. |
| `console` | The full rendered email prints in the terminal running your server. |
| `local` | A local inbox such as mailcrab — see below. |
| `mailgun` | A real email, through Mailgun. |

### See it in a real inbox, locally

Run mailcrab (needs Docker) and switch to `local`:

```bash
docker run --rm -p 1080:1080 -p 1025:1025 marlonb/mailcrab:latest
```

```python
PRBLM_MAILER = {**PRBLM_MAILER, "DELIVERY": "local"}
```

Send a test again and open <http://localhost:1080>. If nothing is listening on port 1025 the
plugin stops with a message saying so. Any SMTP catcher works (mailpit, MailHog); point the
plugin at it with `LOCAL_SMTP_HOST` / `LOCAL_SMTP_PORT`.

### Try a full send

A real send goes only to **confirmed** subscribers — with none, the confirm step says
*Nobody to send to*. Add a confirmed one for testing:

```bash
python manage.py shell -c "
from newsletter.models import Newsletter, Subscription
nl = Newsletter.objects.get(slug='main')
Subscription.objects.get_or_create(newsletter=nl, email_field='test@example.com',
                                   defaults={'subscribed': True})"
```

Then **Who gets it → Proceed → Send now**.

## 6. Walk the signup flow

Worth doing once with `DELIVERY = "local"`, because it exercises the parts that depend on your
URLs and Site record — the ones that fail quietly when something is off:

1. Subscribe at `/newsletter/main/subscribe/`. You land on a **check your inbox** page.
2. The confirmation email appears in mailcrab, in your brand colour.
3. Click its link. The confirm page shows the address and a **Confirm** button, plus **Deny
   subscription** for someone signed up by mistake.
4. Confirm → **"You're all set!"**. Open the same link again and it says *already confirmed*.
5. Under **Subscribers** in the admin the address now shows as confirmed.

If step 3 or 4 gives a 404, see URL order in [§3](#3-urls). If the link points at
`example.com` or won't open, see [Troubleshooting](#troubleshooting).

## 7. Next steps

- Collect subscribers from your site's forms → [Signup forms and groups](signup-forms.md)
- Learn the blocks and the send flow → [Writing and sending newsletters](writing-newsletters.md)
- Bring an existing list across → [Managing subscribers](subscribers.md#importing-a-csv)
- Go live → [Delivery modes and Mailgun](delivery-and-mailgun.md#going-live-with-mailgun)
- Restyle what subscribers see → [Confirmation email and public pages](emails-and-pages.md)

---

## Troubleshooting

Run `python manage.py check` first — it names most of these outright.

| Symptom | Cause and fix |
|---|---|
| No **Newsletters** / **Subscribers** in the admin menu | `prblm_mailer` isn't in `INSTALLED_APPS`, or `migrate` hasn't run. |
| Confirmation link 404s, or the page after it does | The URL bundle is below Wagtail's catch-all ([§3](#3-urls)). Check reports `W004`. |
| Confirmation link points at `example.com` | The Django Site record still has its placeholder domain. Set `WAGTAILADMIN_BASE_URL`; the next signup corrects it (`W002`). |
| Confirmation link is `https://localhost…` and won't open | Set `NEWSLETTER_USE_HTTPS = False` in development (`W003`). |
| A form saves but nobody joins the list | The page's *Collect newsletter subscribers* toggle is off, its panel isn't in `content_panels`, or the submitter left the opt-in checkbox unticked ([signup forms](signup-forms.md)). |
| Image is blank in the preview | `WAGTAILADMIN_BASE_URL` doesn't match how you opened the site, or the dev server isn't serving `/media/`. |
| Social icons missing in a received email | Static files aren't publicly reachable at `WAGTAILADMIN_BASE_URL` — run `collectstatic`. On `localhost`, icons only show in a local inbox. |
| Clicking links in mailcrab records no clicks | Expected: tracking is Mailgun's and only works with `DELIVERY = "mailgun"` ([tracking](tracking.md)). |
| Nothing logged on a dry-run send | Your logging doesn't show INFO from `prblm_mailer`. The admin message still confirms it. |
| `local` mode: "nothing is listening on localhost:1025" | Start mailcrab (above), or set `LOCAL_SMTP_HOST` / `LOCAL_SMTP_PORT`. |
