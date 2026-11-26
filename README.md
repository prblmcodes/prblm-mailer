# prblm-mailer

**A self-hosted newsletter platform for Wagtail.** Write newsletters in the Wagtail admin from
email-safe blocks, collect double-opt-in subscribers from your own forms, target groups of
them, send through Mailgun, and see who opened and clicked — without a third-party newsletter
service, and without changing your project's code beyond a settings block and one URL include.

| | |
|---|---|
| **Wagtail** | 6, 7, 8 |
| **Django** | 5.0 – 6.1 |
| **Python** | 3.12+ |
| **Sending** | Mailgun (via [django-anymail](https://github.com/anymail/django-anymail)) |
| **Status** | Beta — settings and APIs may still change between minor versions |
| **License** | [MIT](LICENSE) |

---

## What you get

- **Compose in the admin.** Newsletters are built from blocks — header, content, image, two
  images, two columns (image + text or text + text), social links, spacer, footer — with a
  live preview and a **Send a test** button. Blocks compile through MJML to HTML that renders
  in Gmail, Outlook and Apple Mail.
- **Double opt-in subscribers.** Nobody receives anything until they click the confirmation
  link. Hard bounces and spam complaints unsubscribe people automatically.
- **Signup from your own forms.** Hook any Django form or Wagtail form-builder page in with one
  line or one mixin. A contact form can offer the newsletter behind an opt-in checkbox.
- **Groups.** Tag subscribers from a signup answer (*Instrument: Guitar*) and send a newsletter
  to just those groups.
- **Open and click tracking** per newsletter, from Mailgun's own tracking.
- **Safe local development.** One setting switches between *log only*, *print to terminal*,
  *a local inbox* (mailcrab/mailpit), and *real Mailgun* — for newsletters, test sends and
  confirmation emails alike.
- **CSV import/export** that reads exports from Mailchimp, Brevo, MailPoet or a spreadsheet,
  shows you what it detected, and never re-adds people who unsubscribed.
- **Branded out of the box.** The confirmation email and the confirm/unsubscribe pages use your
  name and brand colour, and every one is a template you can override.
- **Setup checks.** `manage.py check` names the configuration mistakes that would otherwise fail
  silently (wrong URL order, placeholder domain, https links on an http site…).

## Quick start

Five minutes, nothing sent for real.

**1. Install** — pin a release tag ([releases](https://github.com/prblmcodes/prblm-mailer/releases)):

```bash
pip install "prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.6.1b1"
```

**2. Settings**

```python
from prblm_mailer import with_required_apps

INSTALLED_APPS = with_required_apps(INSTALLED_APPS)   # adds the apps the plugin needs

SITE_ID = 1
WAGTAILADMIN_BASE_URL = "http://localhost:8000"       # your real https URL in production
NEWSLETTER_USE_HTTPS = not DEBUG

PRBLM_MAILER = {
    "FROM_EMAIL": "hello@example.com",
    "FROM_NAME": "Example",
    "BRAND_COLOR": "#2b6cb0",
    "DELIVERY": "console",        # print emails to the terminal; nothing is sent
}
```

**3. URLs** — above Wagtail's catch-all:

```python
urlpatterns = [
    # ...
    path("", include("prblm_mailer.urls_bundle")),
    path("", include(wagtail_urls)),      # must stay last
]
```

**4. Migrate and create the mailing list**

```bash
python manage.py migrate
python manage.py shell -c "
from newsletter.models import Newsletter
Newsletter.objects.get_or_create(slug='main',
    defaults={'title': 'Main list', 'email': 'hello@example.com', 'sender': 'Example'})"
python manage.py check
```

**5. Try it** — in the Wagtail admin open **Newsletters → Add**, add a Content block and a
Footer block, press **Save & send**, then **Send a test**. The rendered email prints in your
server's terminal.

From here, [Installation](docs/installation.md) walks through the full setup, a real local
inbox and the signup flow.

## Documentation

| Guide | What's in it |
|---|---|
| [Installation](docs/installation.md) | Full setup, why each setting exists, local inbox, first-run walkthrough, troubleshooting |
| [Writing and sending newsletters](docs/writing-newsletters.md) | The admin, every block, images, previews, test sends, choosing who gets it |
| [Delivery modes and Mailgun](docs/delivery-and-mailgun.md) | `dry_run` / `console` / `local` / `mailgun`, Django 6.1 `MAILERS`, going live |
| [Signup forms and groups](docs/signup-forms.md) | Plain Django forms, Wagtail form pages, opt-in checkboxes, grouping |
| [Managing subscribers](docs/subscribers.md) | The list, the Subscribers admin, CSV import/export, bounces |
| [Open and click tracking](docs/tracking.md) | Mailgun webhooks, the engagement panel, diagnostic commands |
| [Confirmation email and public pages](docs/emails-and-pages.md) | What subscribers see, and how to restyle it |
| [Configuration reference](docs/configuration.md) | Every setting, startup check, URL and template tag |
| [Upgrading](docs/upgrading.md) | What to do when moving between versions |
| [Development](docs/development.md) | Running the tests across versions, releasing |

What changed in each version: [CHANGELOG](CHANGELOG.md).

## How it fits together

prblm-mailer builds on proven libraries rather than replacing them:

- **[django-newsletter](https://github.com/jazzband/django-newsletter)** stores the mailing
  list and subscribers and runs the double opt-in.
- **[django-anymail](https://github.com/anymail/django-anymail)** talks to Mailgun, for sending
  and for the bounce/open/click webhooks.
- **[mrml](https://github.com/jdrouet/mrml)** compiles the MJML blocks into email-safe HTML.

The plugin adds the Wagtail side: the newsletter editor, the send flow, groups, tracking,
import/export, and the styled emails and pages. It never imports your project's code.

## Limitations

- **Mailgun only** for real sending.
- **One mailing list per site** (`NEWSLETTER_SLUG`); use groups to target parts of it.
- **Sending is synchronous** — one Mailgun call per 1,000 recipients, inside the request. Fine
  into the low thousands of subscribers; there is no background queue yet.

## License

[MIT](LICENSE) © 2026 prblm. Use it, change it and ship it, commercially or not; keep the
copyright notice.
