# Plan: prblm-mailer v1 — feature completion

Status: **DONE ✅** — all phases (A delivery, C tracking, D diagnostics, B forms, E CSV,
F hygiene, G README) implemented and documented. 57 tests pass on Wagtail 6 and 7; beMore
untouched. See README.md for the feature reference and INSTALLATION-GUIDE.md for a first run.

## Goal

A drop-in, self-hosted Wagtail newsletter plugin: compose newsletters, manage subscribers
with double opt-in, group/segment them, send (dry-run / console / local inbox / Mailgun),
track clicks + opens, auto-clean bounces/complaints, import/export subscribers, and diagnose
the Mailgun setup. Installable on **any** Wagtail 6/7 project. **beMore stays untouched** —
it is reference only; we copy + clean, never move or edit it.

## Locked decisions (from the interviews)

- **Delivery = one variable, four modes** (`PRBLM_MAILER["DELIVERY"]`):
  - `"dry_run"` — logs **stats only** (recipient count/list + HTML size). Sends nothing.
  - `"console"` — prints the **full rendered email** (subject/from/to/HTML body) to the
    terminal, per recipient. No inbox app needed.
  - `"local"` — sends to a **local inbox** (mailcrab/mailpit) so it looks like a real client.
  - `"mailgun"` — real send.
  - Keep `DRY_RUN` working as a **back-compat alias** for `"dry_run"`; `DELIVERY` is the switch.
- **Local inbox is turnkey:** `"local"` defaults to SMTP `localhost:1025` (mailcrab/mailpit's
  standard port), overridable — so switching is truly one variable. On `"local"` the plugin
  **checks the port is reachable**; if not, it prints a clear message + the Docker command:
  `docker run -d -p 1080:1080 -p 1025:1025 marlonb/mailcrab` (web UI :1080, SMTP :1025).
- **Forms are explicit, never auto-detected.** A form becomes a newsletter form only when the
  developer opts it in. A form with an email field is **not** auto-counted. A marked form
  **must contain an email field** — the plugin **guards** this and refuses (with a clear log)
  rather than create junk subscribers.
- **Grouping is per-field.** Ship turnkey abstract bases **and** document the manual path.
- **Tracking = clicks + opens**, ported from beMore.
- **Extras in v1:** Mailgun **setup doctor + simulator** commands; **CSV import/export**.
- **Sending stays synchronous.** Document the large-list limit (~a couple thousand);
  revisit async only if a real site needs it.
- **Out of scope for v1:** demo-subscriber command, view-in-browser link, preference center.

---

## Part A — Delivery modes (4, one switch)

### Problem
Sending uses Anymail's Mailgun **batch** API; the body carries `%recipient.*%` placeholders
that **only Mailgun expands**. Console/SMTP would show literal `%recipient.…%` and share one
`to`. So local modes must substitute placeholders in Python and send per-recipient.

### Design
- Add `PRBLM_MAILER["DELIVERY"]` (default `"mailgun"` in prod / resolve from `DRY_RUN`/`DEBUG`
  for back-compat). Precedence: explicit `DELIVERY` wins; else `DRY_RUN`→`"dry_run"`, else
  `DEBUG`→`"dry_run"`, else `"mailgun"`.
- `"dry_run"`: current stats log line, unchanged.
- `"console"` / `"local"`: shared engine — `_send_local()`:
  - loop recipients one at a time,
  - **substitute every `%recipient.X%`** from `subscription_context()` (name,
    unsubscribe_url, oneclick_url, …),
  - send each via `get_connection()`. `"console"` uses Django's console backend; `"local"`
    uses SMTP to `localhost:1025` (default; overridable via a plugin setting).
- Share the substituter with `send_test()` so test emails also render right locally.
- **Pre-task:** grep templates and enumerate every `%recipient.X%` so the substituter covers
  all of them (known: `%recipient.unsubscribe_url%` in footer + header; verify oneclick/others).
- On `"local"`, probe the SMTP port; if unreachable, raise/log the mailcrab Docker hint.

### Tests
- `"console"`/`"local"` (via `locmem`) → one message per recipient in `mail.outbox`, no literal
  `%recipient.` remaining.
- Precedence: `DRY_RUN`/`"dry_run"` beats the local modes; existing DRY_RUN tests stay green.

---

## Part B — Forms + grouping (abstract bases + manual fallback)

### Boundary (already how the code works)
- **Plugin already:** stores groups (`SubscriberTag`), **catches** them from a submission
  (`segments.tags_from_submission`, duck-typing `page.form_fields` for `use_for_grouping` +
  `resolved_group_name`), and **targets + sends** by group (Send-page checkboxes +
  `audience.resolve`). No work here — confirm in docs.
- **Project supplies:** the form; the opt-in; (for grouping) the two field attributes.

### B1 — `subscribe_from_form()` (exists) — document
- Plain Django/custom form: `subscribe_from_form(form.cleaned_data)`, optional
  `groups=[("Instrument","Guitar"), …]`.
- Wagtail form-builder page: `subscribe_from_form(form.cleaned_data, page=self)`.

### B2 — Ship two abstract bases (one-line adoption)
Wagtail form-builder models can't be injected into from outside, but they're **built to be
extended by inheritance**. So the plugin ships:
- `AbstractNewsletterFormPage` (extends `AbstractEmailForm`): adds a **"Collect newsletter
  subscribers" boolean** to the page editor, auto-calls `subscribe_from_form(..., page=self)`
  on submit **only when ticked**, and **enforces the email-field guard**.
- `AbstractGroupingFormField` (extends `AbstractFormField`): adds **`use_for_grouping`** +
  optional **`group_name`** + the `resolved_group_name` property, with panels.
- Host adopts with two one-word base-class swaps:
  ```python
  class FormField(AbstractGroupingFormField): ...
  class FormPage(AbstractNewsletterFormPage): ...
  ```
  Boolean, grouping checkboxes, double-opt-in, and guard all appear automatically. Abstract ⇒
  no plugin migration; the host gets one migration (non-breaking).
- **Manual fallback (documented):** for hosts who can't change the base — add
  `use_for_grouping` + `resolved_group_name` to their field model and call
  `subscribe_from_form()` in their own `process_form_submission` by hand.

### B3 — Signup block — deferred/optional
`sign_group`/`unsign_group` exist for a StreamField signup block, but the block + a public
subscribe view aren't shipped. Out of v1 unless asked.

---

## Part C — Click + open tracking (port from beMore)

- Port `ClickEvent` (clean off `core`), and add **open** events (Mailgun tracks both). Reuse
  the existing `EmailEvent` model for opens if it fits, or add an `OpenEvent`.
- Wire the Anymail **tracking signal** for `clicked` + `opened`. Per-subscriber attribution
  already works: the send sets `merge_metadata` `subscription_id` + `metadata` `broadcast_id`
  + a `broadcast-<pk>` tag. Fall back to email address if metadata is missing.
- **Stats:** `click_stats()` / `open_stats()` on `Broadcast` (total, unique, rate vs sent).
  Re-add the clicks/opens column + panel that were stripped from the Broadcast/Subscriber
  admin views and the Send page.
- **Mailgun side (docs):** enable click + open tracking on the domain. Footer unsubscribe
  keeps `clicktracking="off"` so it isn't rewritten.
- Tests: feed a normalized Anymail event → row created, deduped on retry, attributed to the
  right subscriber; stats compute correctly.

## Part D — Setup doctor + simulator commands (port from beMore)

- `mailgun_doctor` — walks Django config → Mailgun domain → webhooks → our endpoint →
  clicks-Mailgun-vs-us, and says what's broken. Clean off `core`; use plugin models/settings.
- `simulate_mailgun_click` — posts a realistic signed Mailgun `clicked` webhook to our own
  URL so the whole chain can be tested locally (incl. retry dedupe). Clean off `core`.
- Both depend on **Part C** (ClickEvent) — build after it.

## Part E — CSV import / export subscribers

- **Export:** command (and/or admin button) → CSV of current subscribers (email, name,
  status, groups, dates).
- **Import:** command reading CSV (email, name, optional group columns) → create/update
  subscribers, applying groups via `apply_tags`. Guard against messy data (validate email,
  skip blanks).
- **Open question — import consent state:** default new rows to **pending** (must confirm),
  with an explicit `--confirmed` flag for migrating a list you already have consent for.
  Recommend pending-by-default so imports can't silently create un-consented recipients.

## Part F — Bounce / complaint auto-clean (verify, minimal)

- The webhook signal (`handle_mailgun_event`, `HARD_EVENTS`) exists. **Verify** a hard
  bounce/complaint actually flips the subscriber to `unsubscribed=True`, and add a test.

## Part G — README / docs (after code)

- Install → configure → create list → compose → **the 4 delivery modes** (incl. the mailcrab
  Docker command) → get subscribers via your form (Django + Wagtail-builder, with the abstract
  bases and the manual fallback) → grouping → **click/open stats** → CSV import/export →
  `mailgun_doctor`/`simulate_mailgun_click` → going live with Mailgun → **large-list limit note**.
- Cross-link `INSTALLATION-GUIDE.md`.

---

## Open questions to confirm before/while building
1. **CSV import default:** pending (recommended) vs confirmed, with a `--confirmed` flag?
2. **`DELIVERY` naming** confirmed? (keep `DRY_RUN` as alias.)
3. Anything to add/cut before I start Part A.

## Build sequence
1. **A** — delivery modes (`DELIVERY` + `_send_local()` + substituter + port probe); tests.
2. **C** — click + open tracking (needed by D).
3. **D** — `mailgun_doctor` + `simulate_mailgun_click`.
4. **B** — `AbstractNewsletterFormPage` + `AbstractGroupingFormField` (+ manual-path docs).
5. **E** — CSV import/export.
6. **F** — verify bounce/complaint auto-unsubscribe.
7. **G** — README.
8. **Verify** on Wagtail 6 (breakingbeats copy) and 7 (beMore venv); all package tests green;
   **beMore untouched**.
