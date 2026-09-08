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
- **Conditional signup** — a contact form can offer the newsletter with an opt-in checkbox, and
  only subscribe the people who tick it.
- **Four delivery modes, one switch** — log-only, print-to-terminal, a local inbox, or real
  Mailgun.
- **Open + click tracking** — engagement stats per newsletter, from Mailgun’s own tracking.
- **List hygiene** — hard bounces and complaints auto-unsubscribe; unsubscribing is final.
- **Styled by default** — the confirmation email and every public page (confirm, unsubscribe,
  activated) ship branded, and every one of them is a template you can override.
- **CSV import/export** — from the Subscribers admin or the command line — plus two
  **diagnostic commands** for the Mailgun setup.
- **Startup checks** that name the five setup mistakes that otherwise fail silently.

Nothing here imports your project’s code; the package stands alone.

---

## 1. Install

```bash
# in your Wagtail site's virtualenv — latest release
pip install "prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.2.0b1"
```

Or from the release's wheel, which needs neither git nor a build step:

```bash
pip install https://github.com/prblmcodes/prblm-mailer/releases/download/v0.2.0b1/prblm_mailer-0.2.0b1-py3-none-any.whl
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
from wagtail import urls as wagtail_urls

urlpatterns = [
    # ...
    path("", include("prblm_mailer.urls_bundle")),
    path("", include(wagtail_urls)),        # Wagtail's catch-all stays LAST
]
```

> **Order matters — put the bundle ABOVE `include(wagtail_urls)`.** Wagtail's page-serving
> pattern (`^((?:[\w\-]+/)*)$`) matches any path made of plain word segments, so mounted
> below it every newsletter URL is swallowed and 404s. The failure is a confusing one: the
> activation link in the email *works* (it contains an email address, whose `@` and `.` the
> catch-all doesn't match), and then the "subscription activated" page it redirects to 404s.
> A startup check (`prblm_mailer.W004`) detects this by resolving the real URL, and names the
> app that's shadowing it.

That gives you:
- `/mailer/…` — one-click unsubscribe (this package)
- `/newsletter/…` — django-newsletter confirm / unsubscribe
- `/anymail/mailgun/tracking/` — the Mailgun webhook

If you need different prefixes, include the three yourself instead
(`prblm_mailer.urls`, `newsletter.urls`, `anymail.urls`).

> **Startup checks:** prblm-mailer registers Django system checks, so `manage.py check` (and
> server start) tells you clearly what's wrong instead of leaving a silent 404 or a blank
> image:
>
> | | Meaning |
> |---|---|
> | `E001` | `SITE_ID` is missing — confirm/unsubscribe views will 404. |
> | `W001` | `WAGTAILADMIN_BASE_URL` is unset — email links/images fall back to the Wagtail Site. |
> | `W002` | The Site domain is still `example.com` — confirmation links point nowhere. |
> | `W003` | `NEWSLETTER_USE_HTTPS` is on for an `http` base URL — the link won't open. |
> | `W004` | Something else answers the newsletter URLs (usually Wagtail's catch-all, mounted too early). |

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

### What “the list” is (and how it differs from groups)

That `Newsletter` row **is** the mailing list — a django-newsletter object holding the list's
title, sender identity and its subscribers. `PRBLM_MAILER["NEWSLETTER_SLUG"]` names which one
this package uses, which is why the slug you create has to match (`"main"` by default). It is
not a group, and not a category; it is the thing people subscribe *to*.

django-newsletter can hold **several** lists, and each subscriber belongs to one specific
list. This package sends to **one** list — the one named by `NEWSLETTER_SLUG`. Point that
setting at another slug and everything follows it, but there is no per-broadcast list picker.

**Groups are the layer inside a list.** Everyone lives on the one list; a group tags them with
an answer they gave at signup (*Instrument: Guitar*), so a newsletter can target a slice of it
(§7). So:

| | What it is | How many | How someone joins |
|---|---|---|---|
| **List** (`Newsletter`) | The mailing list itself | One in use, set by `NEWSLETTER_SLUG` | Signs up + confirms |
| **Group** (`SubscriberTag`) | A tag on a subscriber | As many as your form fields make | Answers a grouping field |

That's the deliberate split: separate lists would mean separate confirmations, separate
unsubscribes and people signing up twice. One list plus groups gives you targeting without
any of that.

### The Subscribers listing is read-only

You can read it, search it, export it, import into it, and delete from it — but not hand-edit
a row. Subscription state is opt-in/confirm/unsubscribe bookkeeping, and typing over it is how
you end up mailing someone who never confirmed. People join via a signup form's double opt-in,
and leave via unsubscribe or a hard bounce, so there is no Edit button on a subscriber.

---

## 5. Sending & testing — the four delivery modes

Switch by changing one setting, `PRBLM_MAILER["DELIVERY"]`:

| Mode | What happens | Needs |
|---|---|---|
| `dry_run` | Logs recipient count + size. Sends nothing. | — |
| `console` | Prints the full rendered email to the terminal, one per recipient. | — |
| `local` | Sends to a local inbox (mailcrab/mailpit) — looks like a real client. | a local inbox |
| `mailgun` | Real send via Anymail’s Mailgun backend. | Mailgun (see §11) |

`console` and `local` fill in the per-recipient merge fields themselves (Mailgun isn’t
involved), so the email you see is complete.

Only `mailgun` produces **open/click tracking**, for the same reason: Mailgun is what rewrites
links and injects the open pixel. Links in a `console`/`local` email are your plain URLs, so
clicking them records nothing (§8).

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
  `WAGTAILADMIN_BASE_URL`), and Django seeds that record as `example.com` — which is why an
  otherwise-correct setup mails out dead `https://example.com/...` confirmations.
  **The plugin repairs this for you:** while the domain is still the untouched `example.com`
  placeholder, the next signup copies the host from `WAGTAILADMIN_BASE_URL` into it, and a
  startup check (`prblm_mailer.W002`) warns until that happens. A domain you have set
  yourself is never overwritten. To do it by hand:
  ```python
  # Django admin → Sites, or a shell:
  Site.objects.filter(id=1).update(domain="localhost:8000")   # your real domain in production
  ```
- **http vs https** comes from `NEWSLETTER_USE_HTTPS` (defaults to **True**). On a local dev
  server (which is http) the link becomes `https://localhost:8000/...` and won’t open — set:
  ```python
  NEWSLETTER_USE_HTTPS = not DEBUG      # http locally, https in production
  ```
  A startup check (`prblm_mailer.W003`) flags the mismatch, since the symptom — a link that
  simply refuses to open — says nothing about its cause.
- **It arrives styled.** django-newsletter's own confirmation template is bare HTML; the
  plugin renders its own in place of it — a centred card using your `BRAND_COLOR`, the same
  Montserrat/Helvetica stack as the MJML blocks, a real button, a paste-able fallback link,
  and a preheader. It ships at
  `prblm_mailer/templates/prblm_mailer/optin/subscribe.html`.

  **To restyle it**, copy that file into your project as
  `templates/newsletter/message/subscribe.html` and edit freely — a host template of that
  name wins over both the plugin's and django-newsletter's, and the plugin steps aside as
  soon as it sees one. Keep the activation link intact:
  ```django
  <a href="{{ site_url }}{{ subscription.subscribe_activate_url }}">Confirm</a>
  ```
  Context available: `newsletter`, `subscription`, `site`, `site_url`, plus `brand_color` and
  `from_name` from your `PRBLM_MAILER` settings. The plain-text half
  (`subscribe.txt`) stays django-newsletter's unless you override that too.

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

**Letting people opt out (a contact form that also offers the newsletter):** add a
**checkbox** field — “Keep me posted”, say — and tick **“Use as the newsletter opt-in”** on
it. From then on that page only subscribes submitters who ticked the box; everyone else just
sends the form. Their submission is still stored and still emails you as normal — only the
list is skipped, and no confirmation email goes out.

- **Ticked = subscribe.** For an opt-*out* form (box starts ticked, unticking declines), set
  the field's **default value** to checked in the page editor.
- It must be a **checkbox** — the one field type with an unambiguous "no". Anything else is
  rejected in the editor, and ignored at submission if flagged some other way.
- A field marked as the opt-in but **missing from the submission counts as declined**;
  silence is not consent.
- **Only the first** marked field is used — two consent checkboxes is a mistake, not a rule.
- A page with **no** opt-in field is unchanged: every submission is offered the list, exactly
  as before.

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

A host field model can carry `use_for_optin` (on a `checkbox` field) the same way, and the
opt-in check honours it — the plugin duck-types this attribute too.

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

> **Tracking works under `DELIVERY="mailgun"` only.** Clicks and opens are counted by
> Mailgun, which rewrites every link and adds the open pixel as it sends, then reports back
> over the webhook. Under `dry_run`, `console` or `local` (mailcrab/mailpit) no Mailgun is
> involved, so nothing rewrites the links and no webhook ever fires — clicking a link in a
> mailcrab message records **nothing**, and the Engagement panel stays empty. That's expected,
> not a fault. To exercise the tracking path locally, use `simulate_mailgun_click` below.

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

## 9. The public pages (confirm, unsubscribe, activated)

django-newsletter serves the pages people land on from your emails:

| Path | When they see it |
|---|---|
| `/newsletter/<slug>/subscription/<email>/subscribe/activate/<code>/` | The link in the confirmation email |
| `/newsletter/<slug>/subscribe/activation-completed/` | After they confirm |
| `/newsletter/<slug>/unsubscribe/` | Unsubscribe form |
| `/newsletter/<slug>/unsubscribe/activation-completed/` | After they unsubscribe |
| `/newsletter/<slug>/subscribe/email-sent/` | "Check your inbox" |
| `/mailer/deny/` | After declining a signup from the confirm page |
| `/mailer/unsubscribe/<token>/` | The one-click List-Unsubscribe link mail clients show |

**They arrive styled, and they say something useful.** django-newsletter's own versions are
unstyled and thin, so the plugin ships replacements: a centred card with your `FROM_NAME` in
the header bar, `BRAND_COLOR` on the buttons, and copy written for the person reading it. The
CSS is inline and self-contained, because these pages get opened mid-flow from an email client
and can't depend on your asset pipeline — and no webfonts are fetched on the visitor's behalf
(add your own via the `header` block).

Three behaviours worth knowing, all of which the stock templates get wrong:

- **The activation code is hidden.** The default template renders the whole form, so a long
  random code the visitor can't use and mustn't edit sits in a text box. The plugin posts it
  as a hidden field — same round-trip, off the screen.
- **A re-used link says so.** Follow an already-confirmed link and you get *"Already
  confirmed — nothing more to do"* rather than a form that looks like it failed. Same for an
  already-unsubscribed link.
- **"Deny subscription".** If someone was signed up who didn't want to be (a typo, or a
  stranger using their address), the confirm page offers a decline button that deletes the
  pending signup and kills the link. It can never remove a confirmed subscriber — only a
  still-unconfirmed one. *Cancel* leaves the link usable later.

**To restyle**, pick the level you need.

*Wrap them in your real site layout* — create `templates/newsletter/common.html` in your
project (it wins over the plugin's) and hand the page body to your own base:

```django
{% extends "base.html" %}
{% block content %}{% block body %}{% endblock %}{% endblock %}
```

*Keep the layout, change the look* — copy the plugin's shell out of the package and edit the
CSS in it (a template can't extend another of the same name, so copy rather than extend):

```bash
python -c "import prblm_mailer,pathlib;print(pathlib.Path(prblm_mailer.__file__).parent/'templates/newsletter/common.html')"
# copy that file to  templates/newsletter/common.html  in your project
```

*Change one page only* — override just that template, e.g.
`templates/newsletter/subscription_subscribe_activated.html`. The full list of page names is
in `newsletter/templates/newsletter/` inside django-newsletter.

Two useful tags are available in any of these: `{% load prblm_mailer_tags %}` then
`{% mailer_setting "BRAND_COLOR" %}` or `{% mailer_setting "FROM_NAME" %}`.

---

## 10. CSV import / export

**In the admin:** *Subscribers* → **Import CSV** / **Export CSV** in the header. Export
downloads the whole list; import takes a file with an `email` column and asks one question —
whether you already hold these people's consent.

- **Unticked (the default)** — everyone arrives **pending**: on the list, never emailed until
  they confirm for themselves.
- **Ticked** — they arrive confirmed, and will receive your next newsletter. Only for a list
  whose consent you actually hold.

Either way **no confirmation emails are sent by an import**. Mailing a freshly imported list
in one go is the fastest way to get a sending domain blocked.

**On the command line**, same rules:

```bash
python manage.py export_subscribers --output list.csv
python manage.py import_subscribers list.csv               # imports as PENDING
python manage.py import_subscribers list.csv --confirmed   # only for a list you have consent for
```

CSV columns: `email` (required), `name`, `groups` (`"Group: Value; Group2: Value2"`). Import
skips invalid/blank emails, applies groups, never sends opt-in emails, and never downgrades an
already-confirmed subscriber. Admin and command line share one implementation
(`prblm_mailer/csv_io.py`), so an export round-trips through either.

---

## 11. Going live with Mailgun

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

## Upgrading

**To 0.2.0b1 from 0.1.0b1:** this release adds `use_for_optin` to `AbstractGroupingFormField`,
so hosts that use the abstract form bases must generate a migration for their own app:

```bash
pip install --upgrade "prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.2.0b1"
python manage.py makemigrations <your app>     # picks up the new field
python manage.py migrate
python manage.py check                         # confirms the setup checks pass
```

Nothing else is required, and no existing behaviour changes: a form with no opt-in checkbox
subscribes every submission exactly as before. If you had overridden
`newsletter/message/subscribe.html` or `newsletter/common.html`, your versions still win —
the package only fills in where you haven't.

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

114 tests, run against **both** Wagtail 6 and 7 — the two differ in admin internals often
enough that a green run on one proves little about the other.

The suite runs on both Wagtail 6 and 7.

## Cross-version note

The shipped migrations work on Wagtail 6 and 7. If you install into a host **older** than the
version the migrations were generated on and a StreamField migration won’t load, regenerate
the initial migration against your host’s Wagtail version.

See `INSTALLATION-GUIDE.md` for a first-run walkthrough and `PLAN-v1.md` for the build plan.
