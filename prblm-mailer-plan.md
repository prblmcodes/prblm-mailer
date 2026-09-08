# prblm-mailer — build plan

Phased plan to extract the beMore newsletter into a standalone, pip-installable
package. Turns `prblm-mailer-brief.md` (the contract) into a file-by-file checklist.

## Ground rules

- **beMore is never modified.** Its `mailer/` app keeps working as-is. We only *read*
  it to copy and clean code into this new package.
- **This directory is self-contained.** Nothing in `prblm_mailer/` imports `core` or
  anything else from beMore. It installs into a fresh site with settings only.
- **Local install for now** — `pip install -e ./prblm-mailer`. Git/PyPI later.
- **Extract, don't rewrite.** Keep working code (django-newsletter, django-anymail, mrml).
  Only cut beMore-specific couplings and parameterize fingerprints.

## Decisions locked (Aaron signed off)

| Question | Decision |
| --- | --- |
| Subscriber model | **Keep django-newsletter (A).** No `AbstractSubscriber` rewrite this round. |
| Sending | **Synchronous.** No Celery, no `django-tasks`, no async. One Mailgun batch call. |
| Mailgun client | **Keep django-anymail.** Not a hand-rolled raw API module. |
| Click tracking | **Deferred to v2.** Needs per-site DNS + Cloudflare; not "installs with settings." |
| Grouping | **Optional feature**, off unless the host site has a form-builder page. |

## Extra subscriber fields — resolved: per-site profile model

Brief's "done" wants the proof site to have "its own subscriber model, with a field
beMore's doesn't." With **A** (keep django-newsletter) the subscriber *is*
`newsletter.Subscription`, same everywhere. A site that needs extra fields defines its
own tiny profile model, `OneToOne` → `Subscription`:

```python
# host site, NOT the package
class SubscriberProfile(models.Model):
    subscription = models.OneToOneField(
        "newsletter.Subscription", on_delete=models.CASCADE, related_name="profile")
    genre = models.CharField(max_length=80, blank=True)   # whatever that site needs
```

- Package never imports it; host owns it. Sites with no extra fields skip it.
- No `AbstractSubscriber`, no `SUBSCRIBER_MODEL` setting, no swappable-model machinery.
- Satisfies the brief's "extra field" line — the field lives in the site's profile.
- The proof site (Breaking Beats) defines one such profile with at least one field, so
  the pattern is exercised for real.

---

## Target package layout

```
prblm-mailer/                      # repo root (this directory)
├── pyproject.toml                 # makes it pip-installable
├── README.md                      # install + every setting
├── prblm-mailer-brief.md          # the contract
├── prblm-mailer-plan.md           # this file
├── prblm_mailer/                  # the Django app (importable name)
│   ├── __init__.py
│   ├── apps.py
│   ├── conf.py                    # settings object + defaults (NEW)
│   ├── models.py                  # Broadcast, SubscriberTag, EmailEvent
│   ├── audience.py
│   ├── segments.py                # grouping (optional feature)
│   ├── sending.py                 # anymail + mrml, footer from settings
│   ├── subscriptions.py           # opt-in glue over django-newsletter
│   ├── signals.py                 # Mailgun webhook receiver
│   ├── views.py
│   ├── urls.py
│   ├── wagtail_hooks.py
│   ├── blocks.py                  # MJML email blocks, BRAND from settings
│   ├── migrations/
│   │   └── 0001_initial.py        # ONE clean migration
│   ├── templates/prblm_mailer/    # renamespaced from mailer/
│   ├── static/prblm_mailer/
│   └── management/commands/
│       ├── mailgun_doctor.py      # v2 (with click tracking) — or ship read-only now
│       └── simulate_mailgun_click.py   # v2
└── tests/
    ├── settings.py                # minimal test project settings
    └── test_*.py                  # send, opt-in, unsubscribe
```

Package name `prblm_mailer` (underscore, importable). Repo/dir `prblm-mailer` (hyphen).

---

## Settings surface (host site adds only this)

```python
INSTALLED_APPS = [..., "newsletter", "anymail", "prblm_mailer"]

PRBLM_MAILER = {
    "NEWSLETTER_SLUG": "main",              # the newsletter list this site sends
    "FROM_EMAIL": "hello@example.com",
    "FROM_NAME": "Example",
    "REPLY_TO": "",                          # optional
    "POSTAL_ADDRESS": "",                    # footer identity
    "CONTACT_EMAIL": "",                     # footer identity
    "BRAND_COLOR": "#fd6f29",                # default; override per site
    "HEADING_FONT": "Montserrat",
    "BODY_FONT": "Roboto",
    "DRY_RUN": DEBUG,                         # log instead of send
}

ANYMAIL = {                                  # standard anymail, EU hardcoded in package
    "MAILGUN_API_KEY": env("MAILGUN_API_KEY"),
    "MAILGUN_SENDER_DOMAIN": "mg.example.com",
    "MAILGUN_WEBHOOK_SIGNING_KEY": env("MAILGUN_WEBHOOK_SIGNING_KEY"),
    "WEBHOOK_SECRET": env("ANYMAIL_WEBHOOK_SECRET"),
}
```

```python
path("mailer/", include("prblm_mailer.urls")),
path("anymail/", include("anymail.urls")),
```

`prblm_mailer/conf.py` holds every default so a host site sets only what differs.

---

## The couplings to cut (found in beMore's mailer)

Each is a place beMore's mailer reaches into beMore. In the package, each becomes a
setting, a callback, or is dropped.

| # | Coupling in beMore | Fix in package |
| --- | --- | --- |
| 1 | `sending.py`: `from core.models import SiteConfig` (footer name/address/email) | Read from `PRBLM_MAILER` settings. **Hard blocker.** |
| 2 | 3 data migrations seed a beMore Newsletter (`the-learning-scientist`) | Drop. Host site creates its own Newsletter (admin or a documented one-liner). |
| 3 | 27 migrations, some referencing deleted models | Single clean `0001_initial`. |
| 4 | `BRAND = "#fd6f29"`, Montserrat/Roboto, "Be More" hardcoded in templates | `conf.py` defaults, injected into block context + `email.html`. |
| 5 | `newsletter_page.html` — vestigial, hardcoded "Be more" logo | Drop, don't copy. |
| 6 | `segments.py` grouping assumes a form-builder page | Keep (already duck-typed). Document as optional; no-op without such a page. |
| 7 | `subscribe_from_form(cleaned_data)` shaped for a Wagtail form submission | Keep the API; document the expected dict shape. |
| 8 | `django.contrib.sites` `on_site` auto-linking (SITE_ID) | Keep; host site already has sites framework (Wagtail requires it). |

Direction note: beMore's `core` *calls into* mailer (`subscribe_from_form`, `sign_group`).
That's a host *using* the package — expected, stays in beMore. Only mailer→core is cut.

---

## Phases (maps to the brief's Mon–Fri shape)

### Phase 1 — Skeleton that installs empty
- `pyproject.toml`, `prblm_mailer/` app, `apps.py`, empty `conf.py`, `tests/settings.py`.
- Prove `pip install -e ./prblm-mailer` works and the app loads in a bare test project.
- **Done when:** `python -m pytest` runs (even with 0 tests) and the app appears in
  `INSTALLED_APPS` without importing beMore.

### Phase 2 — Models + one clean migration
- Copy `Broadcast`, `SubscriberTag`, `EmailEvent` from beMore's `models.py`.
- Drop `sent_html`/click fields tied to click tracking? No — keep the columns, they're
  harmless; just don't wire the webhook. (Decide: ship `ClickEvent` model but inert.)
- Regenerate a single `0001_initial`. No data migrations.
- **Done when:** `migrate` builds the schema on the test DB from one migration.

### Phase 3 — Sending (anymail + mrml), footer from settings
- Copy `sending.py`. Replace the `core.models.SiteConfig` import with `conf.py` reads.
- Copy `subscriptions.py` (opt-in over django-newsletter), `audience.py`.
- Wire `DRY_RUN` — log the compiled message instead of posting when true.
- **Done when:** a test can build a Broadcast and `send_broadcast()` logs (DRY_RUN) the
  MJML-compiled HTML with the right From/footer from settings.

### Phase 4 — Wagtail admin, blocks, templates, fingerprint hunt
- Copy `blocks.py` — `BRAND` and fonts come from `conf.py`.
- Copy `wagtail_hooks.py`, `views.py`, `urls.py`, `signals.py`.
- Renamespace `templates/mailer/` → `templates/prblm_mailer/`; strip "Be More" text.
- Drop `newsletter_page.html`.
- **Done when:** the Newsletters/Subscribers admin, send page, and email blocks work in
  the test project with default (non-beMore) branding.

### Phase 5 — Prove on a second site + tests + README
- Install into the second site (per brief: Breaking Beats) with **DRY_RUN / console only**.
  Create newsletter, add a subscriber, trigger a send, see it logged. Nothing real sent.
- Tests: campaign send, subscriber opt-in, unsubscribe (brief's required three).
- `README.md`: install (local editable), every setting, "host runs its own worker" is
  N/A (sync), how to create the site's Newsletter row.
- **Done when:** the three tests pass and the second site sends (to console) end to end.

### Deferred to v2 (write in `IDEAS.md`, don't build)
- Click tracking (ClickEvent webhook, `mailgun_doctor`, `simulate_mailgun_click`,
  Cloudflare/DNS). Ship the model inert; wire nothing.
- True `AbstractSubscriber` swappable model (option B).
- Async sending via `django-tasks`.

---

## Safety notes

- **Second-site DB may be a prod clone.** Before configuring a real Mailgun key there,
  check the subscriber table. `DRY_RUN`/console only until certain. (Brief's warning.)
- **Leave nothing behind on the second site they didn't ask for.** Note anything added
  so it can be reverted.
- **Versions:** pin Wagtail `7.4.x` / Django `5.2.x` in `pyproject.toml` — same as beMore.
  Native `django.tasks` is Django 6.0; irrelevant since we're sync.

## Local install quickref

```bash
# from the site that will use it (editable, live edits)
pip install -e /path/to/prblm-mailer

# later: git, once it's its own repo
pip install git+ssh://git@github.com/prblm/prblm-mailer.git
```
