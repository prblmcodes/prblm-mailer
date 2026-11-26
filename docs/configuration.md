# Configuration reference

- [`PRBLM_MAILER` settings](#prblm_mailer-settings)
- [Other settings the plugin relies on](#other-settings-the-plugin-relies-on)
- [Startup checks](#startup-checks)
- [URLs](#urls)
- [Management commands](#management-commands)
- [Template tags](#template-tags)
- [Python API](#python-api)

---

## `PRBLM_MAILER` settings

All plugin settings live in one dictionary. Set only what differs from the default.

```python
PRBLM_MAILER = {
    "NEWSLETTER_SLUG": "main",
    "FROM_EMAIL": "news@example.com",
    "FROM_NAME": "Example",
    "REPLY_TO": "",
    "BRAND_COLOR": "#2b6cb0",
    "DELIVERY": "mailgun",
    "LOCAL_SMTP_HOST": "localhost",
    "LOCAL_SMTP_PORT": 1025,
}
```

| Key | Default | Meaning |
|---|---|---|
| `NEWSLETTER_SLUG` | `"main"` | Slug of the django-newsletter list this site uses. |
| `FROM_EMAIL` | `""` | Sender address. Required for real sends; with Mailgun it must be on your sending domain. |
| `FROM_NAME` | `""` | Sender display name. Also the wordmark on the public pages. |
| `REPLY_TO` | `""` | Optional reply-to address for newsletters. |
| `BRAND_COLOR` | `"#2b6cb0"` | Default button colour; accent of the confirmation email and public pages. |
| `DELIVERY` | see below | `"dry_run"`, `"console"`, `"local"` or `"mailgun"` — [delivery modes](delivery-and-mailgun.md). |
| `LOCAL_SMTP_HOST` | `"localhost"` | Where `local` mode sends. |
| `LOCAL_SMTP_PORT` | `1025` | Port for `local` mode (mailcrab/mailpit's default). |
| `DRY_RUN` | `None` | Older alias: `True` means `DELIVERY = "dry_run"`. Prefer `DELIVERY`. |

When `DELIVERY` isn't set, it is `"dry_run"` if `DEBUG` (or `DRY_RUN`) is on, and `"mailgun"`
otherwise.

Mailgun's keys and region don't go here — they go in Anymail's `ANYMAIL` setting
([going live](delivery-and-mailgun.md#going-live-with-mailgun)).

## Other settings the plugin relies on

| Setting | Why |
|---|---|
| `INSTALLED_APPS` | Use `with_required_apps(INSTALLED_APPS)` — [what it adds](installation.md#what-with_required_apps-adds-and-why). |
| `SITE_ID` | django-newsletter needs the sites framework. `1` is fine. |
| `WAGTAILADMIN_BASE_URL` | Base for every absolute URL in emails: links, images, icons. |
| `NEWSLETTER_USE_HTTPS` | django-newsletter's switch for `https` in confirmation links. Use `not DEBUG`. |
| `ANYMAIL` | Mailgun keys, region and webhook secrets. |
| `EMAIL_BACKEND` or `MAILERS["default"]` | The mailer `mailgun` mode sends through — Anymail's Mailgun backend. |

## Startup checks

`python manage.py check` (and every server start) runs these. Each names a mistake that would
otherwise fail silently.

| Check | Means | Fix |
|---|---|---|
| `prblm_mailer.E001` | `SITE_ID` isn't set; confirm/unsubscribe pages will 404. | `SITE_ID = 1` |
| `prblm_mailer.W001` | `WAGTAILADMIN_BASE_URL` isn't set; email links fall back to the Wagtail Site. | Set it. |
| `prblm_mailer.W002` | The Site domain is still `example.com`; confirmation links point nowhere. | Set `WAGTAILADMIN_BASE_URL` (fixed on the next signup), or set the domain by hand. |
| `prblm_mailer.W003` | `NEWSLETTER_USE_HTTPS` is on but the site is http; the link won't open. | `NEWSLETTER_USE_HTTPS = not DEBUG` |
| `prblm_mailer.W004` | The newsletter URLs aren't mounted, or something else answers them (usually Wagtail's catch-all placed first). | Mount the bundle above `include(wagtail_urls)`. |

## URLs

`path("", include("prblm_mailer.urls_bundle"))` mounts:

| Prefix | From | Purpose |
|---|---|---|
| `/mailer/unsubscribe/<token>/` | prblm-mailer | One-click unsubscribe (the `List-Unsubscribe` header) |
| `/mailer/deny/` | prblm-mailer | Decline a pending signup |
| `/newsletter/…` | django-newsletter | Subscribe, confirm and unsubscribe pages |
| `/anymail/mailgun/tracking/` | django-anymail | Mailgun webhooks: bounces, complaints, opens, clicks |

For other prefixes, include `prblm_mailer.urls`, `newsletter.urls` and `anymail.urls`
yourself. Always above Wagtail's catch-all.

The admin pages (Send, confirm, duplicate, import, export) are registered through Wagtail
hooks and live under `/admin/`.

## Management commands

| Command | What it does |
|---|---|
| `import_subscribers FILE [--dry-run] [--confirmed] [--map FIELD=COLUMN] [--newsletter SLUG]` | Import a CSV — [details](subscribers.md#from-the-command-line). |
| `export_subscribers [--output FILE] [--newsletter SLUG]` | Export the list as CSV. |
| `mailgun_doctor [--probe]` | Check the Mailgun setup end to end — [details](delivery-and-mailgun.md#going-live-with-mailgun). |
| `simulate_mailgun_click [--broadcast ID] [--subscriber ID] [--url URL] [--event-id X]` | Post a signed test click to your own webhook — [details](tracking.md#testing-it-locally). |

## Template tags

`{% load prblm_mailer_tags %}` gives you:

| Tag | Use |
|---|---|
| `{% mailer_setting "BRAND_COLOR" %}` | Any `PRBLM_MAILER` value, e.g. in overridden public pages. An optional second argument is the fallback. |
| `{% email_image image "width-600" as img %}` | An email-safe rendition: WebP/AVIF become PNG, other formats are kept. For your own email templates. |

## Python API

| Import | Use |
|---|---|
| `prblm_mailer.with_required_apps(apps)` | Your `INSTALLED_APPS` plus the plugin's dependencies, in the right order. |
| `prblm_mailer.subscriptions.subscribe_from_form(cleaned_data, page=None, groups=None)` | Start a double opt-in from any form — [signup forms](signup-forms.md#the-one-function). |
| `prblm_mailer.form_pages.NewsletterFormMixin` | Mixin for Wagtail form pages: adds *Collect newsletter subscribers*. |
| `prblm_mailer.form_pages.AbstractGroupingFormField` | Base for form fields: adds grouping and opt-in options. |
