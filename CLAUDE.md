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
- `social.py` — the Social links block's platform list (slug → label + brand colour). Data
  only, no Django imports, because `scripts/build_icons.py` reads the same list; the script
  refuses to run if its artwork and this list disagree about slugs.
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
  `read_table`, `detect_columns`, `parse_groups`), shared by the management commands and the
  admin's Import/Export buttons so the two can't drift on consent semantics. `import_rows`
  takes an optional `mapping` (explicit columns) and `dry_run` (count, write nothing) — the
  admin's preview *is* a dry run, so it can't promise what the import won't do.
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

## 0.3.0b1 changes (blocks)
Three new body blocks, all registered in `email_body_blocks()`:
- **Social links** (`SocialLinksBlock`) — a ListBlock of platform/url/handle, laid out in a row
  or stacked. **Icons are PNGs**, shipped in `static/prblm_mailer/icons/` and generated offline
  by `scripts/build_icons.py` (needs cairosvg; the package never does at runtime). Gmail strips
  SVG, so PNG is the only portable option — and a PNG's colour is baked in, which is why the
  editable colour is the **chip** behind the glyph, with `_contrast_text()` picking the white or
  dark glyph. Plain (chipless) icons are therefore white-or-dark only, decided by the section's
  text colour. `_icon_url()` makes the static path absolute via `sending.absolute_url` (local
  import: sending → models → blocks would be circular) and returns "" rather than raising, so a
  missing file costs an icon, not the send. Artwork: Simple Icons (CC0), except LinkedIn (they
  had it removed) from Font Awesome, and hand-drawn email/website marks.
- **Two columns (text + text)** (`TwoColumnTextBlock`) — two `_CardBlock`s, each with its own
  background, text colour and button, because two cards sharing one background would just be
  the Content block cut in half.
- **Two images** (`TwoImageBlock`) — adjustable split + optional captions.

Gotchas these three taught us:
- **A nested StructBlock needs its own `form_classname`.** The admin grid in
  `wagtail_hooks.py` targets `>[data-contentpath]`, which reaches direct children only, so a
  card's or a profile's fields stacked full-width until `_CardBlock`/`SocialLinkBlock` got
  `card-fields`/`social-link-fields` of their own. Anything that scopes CSS to these blocks
  goes through `scoped()` there — a bare `.chooser__title` rule would restyle every chooser on
  the host's own pages.
- **mrml honours `background-color` and `border-radius` on `mj-column`** (verified), mapping
  both onto the inner `<td>` — so cards and gaps need no raw tables. A gap is an empty spacer
  `mj-column` whose width is taken *out* of the two content columns; a split pair that doesn't
  total 100 (the original `66-33`) leaves a sliver of background down one edge.
- **Arbitrary HTML in a block goes in `mj-text`, never `mj-raw`.** An `mj-raw` is emitted
  between `</tr>` and `</tbody>` and gets foster-parented *above* the section, losing the
  section background with it (the same trap `email_content.html` documents for buttons).
  `tests/test_blocks.py::test_stays_inside_its_section` pins this.
- **Wagtail 6 + ListBlock in a test fixture:** a raw Python list stays a plain list instead of
  becoming a `ListValue`, and Wagtail 6's post-save indexer then dies on the missing
  `bound_blocks`. Build such fixtures through `to_python`, which is what the database does.

## 0.4.0b1 changes (CSV import from anywhere)
The importer only read a column literally called `email`, so a 686-row export whose column
was `Subscriber` imported **nothing** and said "0 new, 686 skipped" — an empty cell wasn't
even added to `bad_emails`, so there was no hint which column should have been the address.

- **Column detection** (`detect_columns`): header aliases first, then value-sniffing — the
  column where ≥70% of a 20-row sample matches the email pattern. A "notes" column holding
  the odd address can't win. `--map`/the admin dropdowns override it; `NoEmailColumn` is
  raised (not a silent zero) when nothing can be read as an address.
- **`read_table`** sniffs the delimiter (`,;\t|`) and decides the header row itself:
  `csv.Sniffer().has_header()` read `email,status` as *data* and would have eaten somebody's
  first subscriber, so the rule is now "does this row look like data?" — any cell an address,
  or everything numeric. Ragged rows are padded so one short line can't shift later columns.
- **Two-step admin flow** — upload parks the text in a temp file keyed by an unguessable
  token (not the session: a subscriber list has no business in a cookie), then the mapping
  screen shows the detected columns, sample rows and a dry-run count. Tokens are pattern-
  checked before being joined to a path, and stale files are swept on each upload.
- **Status is honoured**: `unsubscribed`/`cleaned`/`bounced`/`complained` rows are skipped and
  counted, so importing another tool's export can't undo an unsubscribe. `Subscribed` holding
  a *date* is not treated as a status (`_looks_like_status`), which the real failing file did.
- **Normalisation**: addresses trimmed + lowercased, matched `__iexact` against existing rows
  so a re-import can't create a second row for the same person, de-duped within the file.
- `ImportResult` is a **4-tuple subclass**, so `created, updated, skipped, bad = import_rows(…)`
  still works; the breakdown (`invalid`/`duplicates`/`opted_out`/`mapping`) rides along as
  attributes with a `summary()` for the admin message.

## 0.5.0b1 changes (subscribe date on import)
`subscribe_date` is a real field on django-newsletter's `Subscription` and a column in the
Subscribers listing, but an import left it NULL — including for confirmed rows, because the
write path uses `.update()` to dodge django-newsletter's auto-consent `save()`, and
`_subscribe()` (which sets the date) lives inside that `save()`.

- **Mappable** — `subscribe_date` joins `MAPPING_KEYS`, so it appears as a dropdown on the
  admin's mapping screen and works with `--map subscribe_date="Joined on"`.
- **`parse_date_value`** handles ISO, `dd/mm/yyyy`, `mm/dd/yyyy`, dotted and dashed forms,
  `17 Sep 2025`, `Sep 17, 2025` and unix timestamps; naive values are made aware in the
  site's `TIME_ZONE`, which is the right reading of a date an export wrote in local time.
- **`detect_date_order`** decides day-first vs month-first *from the column's own values*
  (`17/09` can only be a day) rather than from a setting, defaulting to day-first with no
  evidence, and the result is reported in the preview — a wrong guess is visible, not silent.
- **`Subscribed` is the ambiguous header**: a status word in one export, a date in another.
  `detect_columns` decides by content (`_looks_like_status` / `_looks_like_date`) and never
  lets the status and date mappings claim the same column.
- **Fallbacks**: a mapped date wins; otherwise a confirmed row is dated now and a pending row
  gets nothing (they haven't subscribed yet). An existing date is never overwritten, and an
  unreadable date costs a date, never the subscriber — `ImportResult.unreadable_dates`
  reports the count.
- **First/last name are input-side only.** `Subscription` has one `name_field`; the two
  dropdowns exist because exports split the name, and they are joined on the way in. Storing
  the parts would need a model of our own — deliberately not done.

## 0.5.1b1 changes (groups from a plain column)
`parse_groups` required a colon in every piece, so a mapped column holding plain text
(`Essex`, not `Location: Essex`) produced an empty list — and `apply_tags` returns early on
an empty list, so mapping the column did nothing at all, silently. Same shape as the original
email-column bug: no damage, no message, no effect.

- `parse_groups(raw, default_group=None)` now files a colon-less piece under `default_group`,
  and `import_rows` passes **the mapped column's own header** — so a `Location` column of
  towns becomes the Location group. The `Group: Value` form still wins where present, so the
  plugin's own export round-trips unchanged.
- **Commas are deliberately not separators.** A value is as likely to contain one
  ("Leeds, West Yorkshire") as to be a list; `;` stays the separator.
- `ImportResult.grouped` counts rows that carried a usable group, and the mapping screen says
  so — an empty column now reports "No rows carry a group" instead of looking like it worked.

## Open / deferred items
- ~~Wheel packaging~~ **done** (2026-09-08): `[tool.setuptools.package-data]` in
  `pyproject.toml` + `MANIFEST.in`. Without it a built wheel shipped **zero** templates and no
  JS — an editable install hides this because it reads the source tree. Verify after any
  packaging change by building and counting: the wheel must contain every template, the
  admin JS and the 30 social icon PNGs (28 templates + 31 static files at 0.5.1b1).
- Optional niceties discussed but not built: a **StreamField signup block** + public
  subscribe view, **async sending** for very large lists, a **preference centre**, a
  **view-in-browser** link.
- **Wagtail 8 / Django 6 both shipped** and `pyproject.toml` excludes them (`wagtail<8`,
  `Django<5.3`). Nothing is known to break; the bounds have simply not been tested or widened.

## Style
Match the surrounding code: terse, purposeful comments that explain *why* (the existing code
comments the reasoning, not the mechanics). Keep modules host-agnostic.
