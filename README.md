# prblm-mailer

A self-hosted **newsletter platform for Wagtail**. Write newsletters in the Wagtail admin
from email-safe blocks, manage double-opt-in subscribers, group/segment them, send through
Mailgun, and track opens and clicks — all from a single `pip install` and a settings block.

Works on **Wagtail 6 and 7** (Django 5.0–5.2).

## What you get

- **Compose in the admin** — newsletters (“Broadcasts”) built from MJML blocks, with a live
  email preview and a “send a test” button.
- **Subscribers with double opt-in** — people confirm before they ever receive anything.
- **Groups / segments** — optional; target a newsletter at subscribers who answered a signup
  field a certain way.
- **Four delivery modes, one switch** — log-only, print-to-terminal, a local inbox, or real
  Mailgun.
- **Open + click tracking** — engagement stats per newsletter, from Mailgun’s own tracking.
- **List hygiene** — hard bounces and complaints auto-unsubscribe.
- **CSV import/export** and two **diagnostic commands** for the Mailgun setup.

Nothing here imports your project’s code; the package stands alone.

---

## 1. Install

```bash
# in your Wagtail site's virtualenv — latest release
pip install "prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.1.0b1"
```

Or from the release's wheel, which needs neither git nor a build step:

```bash
pip install https://github.com/prblmcodes/prblm-mailer/releases/download/v0.1.0b1/prblm_mailer-0.1.0b1-py3-none-any.whl
```

Pin the tag, not `main` — tags are immutable, so a rebuild resolves to identical code.
Releases are listed at
[github.com/prblmcodes/prblm-mailer/releases](https://github.com/prblmcodes/prblm-mailer/releases).

Working on the package itself? Clone it and install editable instead:

```bash
git clone https://github.com/prblmcodes/prblm-mailer.git
pip install -e /path/to/prblm-mailer
```

Pulls in `django-newsletter`, `django-anymail`, `mrml`, and `sorl-thumbnail`.

## 2. Settings

```python
from prblm_mailer import with_required_apps

INSTALLED_APPS = with_required_apps(INSTALLED_APPS)   # adds the apps below, de-duplicated

SITE_ID = 1                                       # django-newsletter is per-site (see below)
WAGTAILADMIN_BASE_URL = "https://your-site.com"   # absolute URLs in emails (see below)

PRBLM_MAILER = {
    "NEWSLETTER_SLUG": "main",       # the list you'll create in step 4
    "FROM_EMAIL": "hello@example.com",
    "FROM_NAME": "Example",
    "BRAND_COLOR": "#2b6cb0",        # button colour
    "DELIVERY": "dry_run",           # dry_run | console | local | mailgun (see §5)
}
```

### Why these apps (what `with_required_apps` adds, and why)

`with_required_apps(INSTALLED_APPS)` appends the apps prblm-mailer needs, skipping any
your project already lists (so it won't double-add `anymail` or `sites` if you have them).
It adds:

| App | Why it's needed |
|---|---|
| `prblm_mailer` | The package itself (Newsletters/Subscribers admin, sending, tracking). |
| `newsletter` | **django-newsletter** — the subscriber/list engine + double opt-in. We reuse it rather than reinvent subscribers. |
| `sorl.thumbnail` | An image dependency of django-newsletter. |
| `anymail` | Sends via Mailgun and receives its webhooks (bounces, opens, clicks). |
| `django.contrib.sites` | Django's sites framework — django-newsletter is **per-site** (see `SITE_ID`). |

> **Why can't it be one app that hides the rest?** Django reads `INSTALLED_APPS` once at
> startup to build its app registry, so an app can't register other apps on Django's
> behalf. These are separate apps with their own models/migrations/views, so they must be
> listed — `with_required_apps` just makes that one line instead of five.

### Why `SITE_ID`

django-newsletter is built on Django's **sites framework**: a list belongs to a `Site`, and
its confirm/unsubscribe views look up "the current site" via `SITE_ID`. Without it, those
links 404. It isn't that the plugin supports multiple sites — the library underneath uses
the framework — so `SITE_ID = 1` ("there's one site, it's #1") is all you need. A startup
check errors clearly if it's missing.

### Why `WAGTAILADMIN_BASE_URL`

Emails open in Gmail/Outlook, far from your server, so every link and image must be an
**absolute** URL (`https://your-site/…`), not a relative `/…`. This setting is that base.
It's used to build the **unsubscribe links** and the **image `src`s** in the email.

- **Local value:** exactly how you open the dev server, e.g. `http://localhost:8000`
  (if you browse `127.0.0.1:8000`, use that — a browser treats them as different hosts).
- **Live value:** `https://your-real-domain.com`.

If it's **not set**, prblm-mailer falls back to the current Wagtail Site's URL so links still
resolve, and a startup check warns you — but that fallback can be wrong in email, so set it
explicitly for real sends. (This is also the usual cause of a **blank image in the preview**:
a wrong base URL, or the dev server not serving `/media/`.)

### Settings reference (`PRBLM_MAILER`)

| Key | Default | Meaning |
|---|---|---|
| `NEWSLETTER_SLUG` | `"main"` | Which django-newsletter list to send to. |
| `FROM_EMAIL` | `""` | Sender address (required for real sends). |
| `FROM_NAME` | `""` | Sender display name. |
| `REPLY_TO` | `""` | Optional reply-to address. |
| `BRAND_COLOR` | `"#2b6cb0"` | Default button colour in blocks. |
| `DELIVERY` | resolved | `dry_run` / `console` / `local` / `mailgun`. Unset → `dry_run` in DEBUG, else `mailgun`. |
| `DRY_RUN` | `None` | Back-compat alias; `True` ⇒ `DELIVERY="dry_run"`. |
| `LOCAL_SMTP_HOST` | `"localhost"` | Where `DELIVERY="local"` sends. |
| `LOCAL_SMTP_PORT` | `1025` | mailcrab/mailpit’s standard SMTP port. |

## 3. URLs

One include, mounted at the site root, wires up all three routes at their conventional
paths:

```python
from django.urls import include, path

urlpatterns = [
    # ...
    path("", include("prblm_mailer.urls_bundle")),
]
```

That gives you:
- `/mailer/…` — one-click unsubscribe (this package)
- `/newsletter/…` — django-newsletter confirm / unsubscribe
- `/anymail/mailgun/tracking/` — the Mailgun webhook

If you need different prefixes, include the three yourself instead
(`prblm_mailer.urls`, `newsletter.urls`, `anymail.urls`).

> **Startup checks:** prblm-mailer registers Django system checks, so `manage.py check` (and
> server start) will tell you clearly if `SITE_ID` is missing (error) or
> `WAGTAILADMIN_BASE_URL` is unset (warning) — no more silent 404s or blank images.

## 4. Migrate and create the list

```bash
python manage.py migrate

python manage.py shell -c "
from newsletter.models import Newsletter
Newsletter.objects.get_or_create(
    slug='main',
    defaults={'title': 'Main list', 'email': 'hello@example.com', 'sender': 'Example'},
)"
```

Log into `/admin/` — you’ll see **Newsletters** and **Subscribers** in the menu.

---

## 5. Sending & testing — the four delivery modes

Switch by changing one setting, `PRBLM_MAILER["DELIVERY"]`:

| Mode | What happens | Needs |
|---|---|---|
| `dry_run` | Logs recipient count + size. Sends nothing. | — |
| `console` | Prints the full rendered email to the terminal, one per recipient. | — |
| `local` | Sends to a local inbox (mailcrab/mailpit) — looks like a real client. | a local inbox |
| `mailgun` | Real send via Anymail’s Mailgun backend. | Mailgun (see §10) |

`console` and `local` fill in the per-recipient merge fields themselves (Mailgun isn’t
involved), so the email you see is complete.

**What `DELIVERY` covers:** newsletter **broadcasts**, **test sends**, *and* the **double
opt-in confirmation email** — so with `DELIVERY="local"` the confirmation lands in mailcrab
too, with no `EMAIL_BACKEND` changes. The one email it does **not** control is a Wagtail
form-builder page’s own **submission notification** (the “someone filled in your form” email);
that’s sent by Wagtail’s `AbstractEmailForm` through Django’s standard `EMAIL_BACKEND`. To
see *that* one locally too, point Django at the same inbox:

```python
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST, EMAIL_PORT = "localhost", 1025   # mailcrab/mailpit
```

**The confirmation (opt-in) email — a few django-newsletter details.** Its **content and
activation link are django-newsletter’s**, not the plugin’s (the plugin only routes *how* it’s
sent, via `DELIVERY`). So:

- **Link domain** comes from the `django.contrib.sites` **Site** record (not
  `WAGTAILADMIN_BASE_URL`). Default is `example.com`, so set it:
  ```python
  # Django admin → Sites, or a shell:
  Site.objects.filter(id=1).update(domain="localhost:8000")   # your real domain in production
  ```
- **http vs https** comes from `NEWSLETTER_USE_HTTPS` (defaults to **True**). On a local dev
  server (which is http) the link becomes `https://localhost:8000/...` and won’t open — set:
  ```python
  NEWSLETTER_USE_HTTPS = not DEBUG      # http locally, https in production
  ```
- **It’s plain (unstyled)** — that’s django-newsletter’s default template, by design. To style
  it, override the template in your project:
  `templates/newsletter/message/subscribe.html` (and `.txt`).

**Running a local inbox** (for `DELIVERY="local"`):

```bash
# needs Docker installed; runs mailcrab (no separate install)
docker run --rm -p 1080:1080 -p 1025:1025 marlonb/mailcrab:latest
# read mail at http://localhost:1080  (SMTP on :1025). Add -d to run in the background.
```

If nothing is listening on the port, the plugin fails with this exact hint rather than a
silent error. Point it elsewhere with `LOCAL_SMTP_HOST` / `LOCAL_SMTP_PORT`.

**In the admin:** Newsletters → Add → compose → **Save & send** → the Send page has a live
preview, a **Send a test**, and **Who gets it** (audience). “Send a test” goes to one address
you type and needs no subscribers.

---

## 6. Getting subscribers (signup forms)

The package does **not** ship a form and never auto-detects one — a form only feeds the
newsletter **when you wire it**, so your list stays clean. You keep your own form; you add
one line (or one mixin) that hands the submitted data to the plugin, which then creates a
**pending** subscriber and emails the **double-opt-in** confirmation link. The person only
starts receiving newsletters after they click that link.

The one function everything below uses:

```python
from prblm_mailer.subscriptions import subscribe_from_form
subscribe_from_form(cleaned_data, page=None, groups=None)
```

It finds the email (and name) in `cleaned_data` itself, creates the pending subscriber, and
sends the opt-in. It **never raises**, so it can’t break the visitor’s form submission; it
returns the `Subscription`, or `None` if there was nothing to do (e.g. no email in the data).

> **A signup form must include an email field.** Without an address the plugin refuses (and
> logs) rather than create a junk row.

---

### 6a. A plain Django form

**forms.py**
```python
from django import forms

class NewsletterSignupForm(forms.Form):
    email = forms.EmailField(label="Your email")
    name = forms.CharField(label="Your name", required=False)
```

**views.py**
```python
from django.contrib import messages
from django.shortcuts import redirect, render

from prblm_mailer.subscriptions import subscribe_from_form
from .forms import NewsletterSignupForm

def newsletter_signup(request):
    if request.method == "POST":
        form = NewsletterSignupForm(request.POST)
        if form.is_valid():
            subscribe_from_form(form.cleaned_data)          # ← the only plugin line
            messages.success(request, "Almost there — check your inbox to confirm.")
            return redirect("newsletter_signup")
    else:
        form = NewsletterSignupForm()
    return render(request, "signup.html", {"form": form})
```

Your success message should say *“check your email to confirm”* — they aren’t subscribed
until they click the link.

**Groups (a plain form):** pass `groups` explicitly as `(group_name, answer)` pairs:
```python
class NewsletterSignupForm(forms.Form):
    email = forms.EmailField()
    interest = forms.ChoiceField(choices=[("guitar", "Guitar"), ("drums", "Drums")])

# in the view:
cd = form.cleaned_data
groups = [("Interest", cd["interest"])] if cd.get("interest") else None
subscribe_from_form(cd, groups=groups)     # tags the subscriber "Interest: guitar"
```

---

### 6b. A Wagtail form-builder page — inherit the plugin’s bases (recommended)

Swap two base classes; the “collect subscribers” checkbox, the per-field grouping controls,
and the double-opt-in call all appear automatically.

```python
from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.contrib.forms.models import AbstractEmailForm
from wagtail.fields import RichTextField

from prblm_mailer.form_pages import AbstractGroupingFormField, NewsletterFormMixin


class FormField(AbstractGroupingFormField):                     # ← was AbstractFormField
    page = ParentalKey("FormPage", related_name="form_fields", on_delete=models.CASCADE)


class FormPage(NewsletterFormMixin, AbstractEmailForm):         # ← mixin FIRST
    intro = models.TextField(blank=True)
    thank_you_text = RichTextField(blank=True)

    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("intro"),
        InlinePanel("form_fields", label="Form fields"),
        FieldPanel("thank_you_text"),
        *NewsletterFormMixin.newsletter_panels,     # ← the "Collect newsletter subscribers" checkbox
    ]
```

Then `python manage.py makemigrations && python manage.py migrate`.

**Groups (a form-builder page):** you don’t pass `groups` by hand — in the page editor, tick
**“Use for grouping”** on a **choice field** (e.g. a “Which instrument?” dropdown). Every
submission then tags the subscriber automatically (e.g. *Instrument: Guitar*). No code.

---

### 6c. A Wagtail form-builder page — the manual way (no plugin base classes)

Do by hand exactly what the mixin does for you — useful if you can’t change your base classes.
Three additions: the boolean on the page, the `process_form_submission` hook, and (for
grouping) the two attributes on the field.

```python
from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.contrib.forms.models import AbstractEmailForm, AbstractFormField

from prblm_mailer.subscriptions import subscribe_from_form


class FormField(AbstractFormField):
    page = ParentalKey("FormPage", related_name="form_fields", on_delete=models.CASCADE)

    use_for_grouping = models.BooleanField(default=False)       # ← grouping (optional)
    group_name = models.CharField(max_length=80, blank=True)

    panels = AbstractFormField.panels + [
        FieldPanel("use_for_grouping"),
        FieldPanel("group_name"),
    ]

    @property
    def resolved_group_name(self):
        return self.group_name or self.label


class FormPage(AbstractEmailForm):
    collect_newsletter_subscribers = models.BooleanField(default=False)   # ← the boolean

    content_panels = AbstractEmailForm.content_panels + [
        InlinePanel("form_fields", label="Form fields"),
        FieldPanel("collect_newsletter_subscribers"),
    ]

    def process_form_submission(self, form):                    # ← the hook
        submission = super().process_form_submission(form)      # saves AND returns the submission
        if self.collect_newsletter_subscribers:
            subscribe_from_form(form.cleaned_data, page=self)
        return submission                                       # return this — don't create a second one
```

The two field attributes (`use_for_grouping` + `resolved_group_name`) are exactly what the
plugin looks for by duck-typing, so grouping works identically to 6b.

---

### Gotchas (both Wagtail ways)

- **Mixin must come first:** `class FormPage(NewsletterFormMixin, AbstractEmailForm)` — so its
  `process_form_submission` runs, then delegates via `super()`.
- **Return the submission from `super()`** — don’t also `return self.get_submission_class().objects.create(...)`, or you’ll save the submission twice.
- **Read optional keys with `.get()`** in your own code (e.g. `form_data.get("first_name", "")`) — a missing form field is a `KeyError` with `form_data["first_name"]`.
- **Grouping is choice-fields only** — see §7.
- **The confirmation email obeys `DELIVERY`** (§5), so under `dry_run` it’s only logged. Use
  `console`/`local`/`mailgun` when you want to actually receive it.

## 7. Groups / segments

A grouping field turns a submitted answer into a `(group, answer)` tag on the subscriber —
e.g. a “Which instrument?” dropdown becomes the *Instrument* group. On the Send page these
appear as **checkboxes** under “Who gets it”; tick the groups a newsletter should go to
(nothing ticked = everyone). Answers are stored on the subscriber at signup, so renaming or
deleting the form field later never loses anyone’s group.

**Only choice fields can be grouping fields** — `dropdown`, `radio`, `checkboxes`,
`multiselect`. A free-text (or email/number/date) field would mint a new one-person group on
every submission, so ticking “Use for grouping” on one is rejected in the editor, and ignored
at submission time as a safety net.

---

## 8. Open & click tracking

Engagement comes from **Mailgun’s own tracking**, delivered to the Anymail webhook — the
package runs no redirect or pixel endpoint of its own. To turn it on:

1. In Mailgun, enable **click** and **open** tracking on your sending domain.
2. Point the `clicked`, `opened`, `permanent_fail`, `temporary_fail`, `complained`,
   `unsubscribed` webhooks at `https://your-site/anymail/mailgun/tracking/`.
3. Set `ANYMAIL["WEBHOOK_SECRET"] = "user:pass"` and use the same credentials in the URL.

Then the **Newsletters** list shows Clicks/Opens columns, and a sent newsletter’s **Send
page** shows an Engagement panel (opens/clicks, unique people, rates, top links).
Unsubscribe-link clicks are never counted as engagement.

**Two commands help:**

```bash
python manage.py mailgun_doctor          # checks config → domain → webhooks → endpoint, end to end
python manage.py simulate_mailgun_click  # posts a realistic signed click to your own webhook, locally
```

`mailgun_doctor` talks to the live Mailgun API (needs `requests`). `simulate_mailgun_click`
is fully local — it exercises the real signature check, payload parser, and signal handler;
pass `--event-id X` twice to prove retries are de-duplicated.

## 9. CSV import / export

```bash
python manage.py export_subscribers --output list.csv
python manage.py import_subscribers list.csv               # imports as PENDING
python manage.py import_subscribers list.csv --confirmed   # only for a list you have consent for
```

CSV columns: `email` (required), `name`, `groups` (`"Group: Value; Group2: Value2"`). Import
skips invalid/blank emails, applies groups, never sends opt-in emails, and never downgrades an
already-confirmed subscriber. The two commands round-trip.

---

## 10. Going live with Mailgun

```python
import os
EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
ANYMAIL = {
    "MAILGUN_API_KEY": os.environ["MAILGUN_API_KEY"],
    "MAILGUN_SENDER_DOMAIN": "mg.example.com",
    "MAILGUN_API_URL": "https://api.eu.mailgun.net/v3",   # EU vs US — must match your account
    "MAILGUN_WEBHOOK_SIGNING_KEY": os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"],
    "WEBHOOK_SECRET": os.environ["ANYMAIL_WEBHOOK_SECRET"],   # "user:pass"
}
```

Set `PRBLM_MAILER["DELIVERY"] = "mailgun"`, send yourself a real test, then send for real:
Send page → Who gets it → Proceed → confirm count → Send now. Keep secrets in the
environment, never in code. Run `python manage.py mailgun_doctor` if anything misbehaves.

## Limitations

- **Sending is synchronous** — one Mailgun batch call per 1000 recipients, within the request.
  Fine into the low thousands; for very large lists, put it behind a task runner (a future
  option).

## Running the tests

```bash
cd prblm-mailer
DJANGO_SETTINGS_MODULE=tests.settings python -m django test tests
# or, with pytest installed:  pip install -e ".[test]" && pytest
```

The suite runs on both Wagtail 6 and 7.

## Cross-version note

The shipped migrations work on Wagtail 6 and 7. If you install into a host **older** than the
version the migrations were generated on and a StreamField migration won’t load, regenerate
the initial migration against your host’s Wagtail version.

See `INSTALLATION-GUIDE.md` for a first-run walkthrough and `PLAN-v1.md` for the build plan.
