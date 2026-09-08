# prblm-mailer — project context for Claude Code

This file is the working memory for the **prblm-mailer** package. It captures the goal,
the decisions, the architecture, and the gotchas found while building and testing it, so a
new session has the reasoning that the code/README don't spell out.

Companion docs in this repo (read them for detail):
- `README.md` — the complete feature + setup reference (the "ultimate" guide).
- `INSTALLATION-GUIDE.md` — a 10-minute first-run walkthrough.
- `PLAN-v1.md` — the phased build plan (all phases done).
- `prblm-mailer-brief.md` — the original contract.

## What this is
A **self-hosted newsletter platform for Wagtail**, extracted from an app called *beMore*
into a standalone, `pip`-installable package. Write newsletters in the Wagtail admin from
email-safe MJML blocks, manage double-opt-in subscribers, group/segment them, send via
Mailgun, and track opens/clicks. Installs with a settings block — no host code changes.

Origin: it was beMore's internal `mailer/` app. We **copied + cleaned** it into this package
(never moved/edited beMore). It now imports nothing from any host project.

## Hard constraints / conventions
- **Stands alone.** Never import a host project's code (no `core`, no host models). Config
  comes from a single `PRBLM_MAILER` settings dict via `prblm_mailer/conf.py::get_setting`.
- **Cross-version:** must run on **Wagtail 6 and 7** and **Django 5.0–5.2**. This is the
  central constraint — see "Cross-version notes" below.
- **Local editable install** for now (`pip install -e .`). A built wheel still needs
  `package_data`/MANIFEST for templates/static/js — see "Open items".
- Secrets (Mailgun keys) only ever in the host's env/settings, never in code.

## Key product decisions (settled)
- **Keep django-newsletter** as the subscriber/list engine (don't rebuild subscribers). This
  is why the host also needs `newsletter`, `sorl.thumbnail`, and `django.contrib.sites`
  (django-newsletter is per-site → `SITE_ID`).
- **django-anymail** for Mailgun (sending + webhooks), not raw Mailgun. EU vs US API URL
  matters and is the host's to set.
- **Synchronous sending** (one Mailgun batch call per 1000 recipients, in-request). Fine into
  the low thousands; async is deferred.
- **Grouping is optional and choice-fields-only** (dropdown/radio/checkboxes/multiselect) — a
  free-text grouping field would mint a new group per submission.
- **Four delivery modes, one switch** (`PRBLM_MAILER["DELIVERY"]`): `dry_run`, `console`,
  `local` (mailcrab/mailpit), `mailgun`. This also governs test sends AND the double-opt-in
  confirmation email (so `local` puts the confirmation in mailcrab with no `EMAIL_BACKEND`
  change).

## Architecture (modules in `prblm_mailer/`)
- `conf.py` — `PRBLM_MAILER` defaults + `get_setting()`; `DELIVERY_MODES`.
- `models.py` — `Broadcast` (the newsletter: subject + MJML `StreamField` body, status, sent
  record, `engagement_stats()`, columns), `SubscriberTag` (a `(group, value)` pair, M2M to
  `newsletter.Subscription`), `Subscriber` (read-only proxy over Subscription), `EmailEvent`
  (bounces/complaints), `EngagementEvent` (clicks+opens, one table, `kind` field).
- `blocks.py` + `templates/prblm_mailer/blocks/*.html` — the MJML email blocks. Images use
  `{{ img.full_url }}` (absolute URLs, needed in email).
- `sending.py` — render (MJML→HTML via `mrml`), `DELIVERY` dispatch, `_send_local` (per-
  recipient, substitutes `%recipient.*%` in Python), `_send_mailgun` (Anymail batch),
  `send_test`, `send_broadcast`, `send_optin` (routes django-newsletter's confirmation email
  through `DELIVERY`), `absolute_url`/`_base_url` (falls back to the Wagtail Site URL).
- `subscriptions.py` — `subscribe_from_form(cleaned_data, page=None, groups=None)` (the public
  signup entry point; double opt-in; `.update()` not `.save()` to avoid django-newsletter's
  auto-subscribe side effect), `confirmed_subscriptions()`, sender-identity + site reconcile.
- `segments.py` — grouping: `grouping_specs`, `tags_from_submission`, `apply_tags`,
  `sign_group`; `CHOICE_FIELD_TYPES` guard.
- `form_pages.py` — optional host helpers: `NewsletterFormMixin` (adds "Collect newsletter
  subscribers" toggle + `process_form_submission` double-opt-in) and
  `AbstractGroupingFormField` (adds "Use for grouping" + `group_name` + `resolved_group_name`;
  `clean()` rejects grouping on non-choice fields, and `use_for_optin` on non-checkbox ones).
- **Conditional signup (0.2.0b1):** a `checkbox` field ticked "Use as the newsletter opt-in"
  gates subscribing — ticked subscribes, unticked (or absent: silence isn't consent) skips the
  list while the submission itself still saves and notifies. Enforced in
  `subscriptions._optin_declined` (so *every* caller of `subscribe_from_form` gets it, not just
  the mixin); the field is found by `segments.optin_field_name`, duck-typed like grouping.
  Checkbox-only because it is the one field type with an unambiguous "no". Pages with no such
  field behave exactly as before. **Adds a field to an abstract base → hosts must
  `makemigrations` on upgrade.**
- `audience.py` — `resolve(broadcast)` (confirmed subs, narrowed by chosen groups) + `describe`.
- `signals.py` — Anymail webhook receiver: records clicks/opens (`EngagementEvent`, deduped on
  Mailgun event id, test-sends ignored), auto-unsubscribes hard bounces/complaints, IP-scrub
  on subscriber delete.
- `admin_views.py` + `wagtail_hooks.py` + `templates/prblm_mailer/*` — Newsletters/Subscribers
  snippets, the Send page (preview, test, audience, engagement panel), confirm/duplicate,
  `DELIVERY`-aware success messages.
- `management/commands/` — `mailgun_doctor` (diagnose the live setup end-to-end),
  `simulate_mailgun_click` (post a real signed click webhook locally), `import_subscribers` /
  `export_subscribers` (CSV).
- `checks.py` — Django system checks: `E001` if `SITE_ID` missing, `W001` if
  `WAGTAILADMIN_BASE_URL` unset, `W002` if the Site domain is still `example.com`, `W003` if
  `NEWSLETTER_USE_HTTPS` is on for an http base URL.
- `csv_io.py` — one implementation of the subscriber CSV rules (`export_rows`, `import_rows`,
  `parse_groups`), shared by the management commands and the admin's Import/Export buttons so
  the two can't drift on consent semantics.
- `urls.py` (this package's routes, namespaced `prblm_mailer`), `urls_bundle.py` (one include
  that mounts `/mailer/`, `/newsletter/`, `/anymail/`).
- `__init__.py` — `with_required_apps(INSTALLED_APPS)` / `required_apps()` (import-light; safe
  to call from settings).

## Setup the package expects (host side)
```python
from prblm_mailer import with_required_apps
INSTALLED_APPS = with_required_apps(INSTALLED_APPS)   # + newsletter, anymail, sorl.thumbnail, sites
SITE_ID = 1
WAGTAILADMIN_BASE_URL = "https://your-site.com"
PRBLM_MAILER = {"NEWSLETTER_SLUG": "main", "FROM_EMAIL": "...", "FROM_NAME": "...",
                "BRAND_COLOR": "#...", "DELIVERY": "dry_run"}
# urls.py:  path("", include("prblm_mailer.urls_bundle"))
# then: migrate, and create one Newsletter row with slug == NEWSLETTER_SLUG
```

## Gotchas discovered while testing (don't re-learn these)
- **Two email channels.** `DELIVERY` controls broadcasts, test sends, and the **opt-in
  confirmation**. A Wagtail form-builder page's **own submission notification** is Wagtail's
  `AbstractEmailForm` and uses Django's `EMAIL_BACKEND` — set an SMTP backend to route that to
  mailcrab too.
- **Confirmation link** is built by django-newsletter from the `django.contrib.sites` **Site**
  record (default `example.com`) + `NEWSLETTER_USE_HTTPS` (default **True**). Locally set the
  Site domain to `localhost:8000` and `NEWSLETTER_USE_HTTPS = not DEBUG`, or the link is a
  broken `https://localhost:8000/...`.
- **Opt-in email is plain** — that's django-newsletter's default template; override
  `templates/newsletter/message/subscribe.html` to style it.
- **`dry_run` logs at INFO** — invisible unless the host shows INFO logs; the admin shows a
  "Dry run — nothing sent" message instead. `console` prints the email; `local` → mailcrab.
- **Blank preview image** = wrong `WAGTAILADMIN_BASE_URL` (host/port mismatch) or dev server
  not serving `/media/`.
- **Host `process_form_submission`**: mixin must be the FIRST base; `return` the submission
  from `super()` (don't `objects.create` a second one); read optional keys with `.get()`.

## Cross-version notes (Wagtail 6 vs 7)
- `PreviewableMixin` moved modules (6: `wagtail.models`, 7: `wagtail.models.preview`).
- StreamField migration serialization differs — the **`0001` migration was generated under
  Wagtail 6** (older format) so it loads on **both** 6 and 7. If regenerating a StreamField
  migration, do it on the lowest Wagtail version you support.
- Wagtail 6 `RichTextBlock` needs a `RichText(...)` object, not a raw string (matters in test
  fixtures).
- The test app's page migration pins `('wagtailcore', '__first__')` — a pinned number breaks
  the other Wagtail version.

## Testing
- Suite in `tests/` (settings `tests.settings`; a throwaway `tests/testapp` exercises the form
  bases). Run with Django's test runner (pytest optional):
  ```bash
  DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=. python -m django test tests
  ```
- **Always run on both Wagtail versions** before trusting a change (use two virtualenvs, one
  with Wagtail 6.x, one with 7.x). Current count: ~70 tests, green on both.

## 0.2.0b1 changes (this round)
- **Conditional signup** — see `form_pages.py` above.
- **Site domain self-heal** — `subscriptions._reconcile_site_domain()` copies the host from
  `WAGTAILADMIN_BASE_URL` into the Site row *only while it is still the `example.com`
  placeholder*. The opt-in link is django-newsletter's, built from `Site.objects.get_current()`
  — `_base_url()` can't reach it, so correcting the row is the only lever.
- **Styled opt-in email** — `templates/prblm_mailer/optin/subscribe.html`, rendered by
  `sending._optin_html()`. It defers to `newsletter/message/subscribe.html` when a host (or
  another app) provides one; `_is_django_newsletter_default()` decides by template origin path.
- **One-click unsubscribe pages** — `views.oneclick_unsubscribe` rendered inline HTML strings;
  now three templates under `prblm_mailer/` extending the same shell. The invalid/expired page
  deliberately doesn't say which of the two it was.
- **Styled public pages** — ported from bemore's own overrides (`bemore/templates/newsletter/`):
  a `common.html` shell plus `subscription_activate`, `_subscribe_activated`,
  `_unsubscribe_activated`, and both `_email_sent` pages; `prblm_mailer/subscription_denied.html`
  now extends the shell too. The activate page is the substantive one: it posts
  `user_activation_code` via `.as_hidden` (the stock template puts that random string in a
  visible text box), short-circuits to "already confirmed"/"already unsubscribed" when the
  link is re-used, and wires the existing `prblm_mailer:deny_subscription` view to a Deny
  button. Generic where bemore was not: wordmark is `FROM_NAME`, accent is `BRAND_COLOR`, no
  Google Fonts fetch. Reads settings via `templatetags/prblm_mailer_tags.py` (`mailer_setting`),
  because those views' context is django-newsletter's. Depends on `prblm_mailer` preceding
  `newsletter` in INSTALLED_APPS — `with_required_apps` orders it that way.
- **`W004` URL-ordering check** — the bundle mounted *below* `include(wagtail_urls)` is
  swallowed by Wagtail's catch-all `^((?:[\w\-]+/)*)$`. Diabolical symptom: the activation
  link works (it holds an email address, so `@`/`.` miss the catch-all) but the
  activation-completed page it redirects to 404s. The check resolves the real URL and names
  whichever module answered; `tests/urls_shadowed.py` reproduces the misordering.
- **Subscribers admin** — Import/Export CSV header buttons (`admin_views.export_subscribers` /
  `import_subscribers`), and the Edit button is gone. Removing it needed `get_edit_url() -> None`
  on the index *and* inspect views: a permission-policy override worked on Wagtail 7 but not 6,
  which the cross-version run caught. `SubscriberEditView`'s redirect stays as the URL guard.

## Open / deferred items
- ~~Wheel packaging~~ **done** (2026-09-08): `[tool.setuptools.package-data]` in
  `pyproject.toml` + `MANIFEST.in`. Without it a built wheel shipped **zero** templates and no
  JS — an editable install hides this because it reads the source tree. Verify after any
  packaging change by building and counting: the wheel must contain every template + 1 JS
  (22 templates at 0.2.0b1).
- Optional niceties discussed but not built: a **StreamField signup block** + public
  subscribe view, **async sending** for very large lists, a **preference centre**, a
  **view-in-browser** link.
- **Wagtail 8 / Django 6 both shipped** and `pyproject.toml` excludes them (`wagtail<8`,
  `Django<5.3`). Nothing is known to break; the bounds have simply not been tested or widened.

## Style
Match the surrounding code: terse, purposeful comments that explain *why* (the existing code
comments the reasoning, not the mechanics). Keep modules host-agnostic.
