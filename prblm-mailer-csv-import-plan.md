# prblm-mailer — robust "import subscribers from any CSV"

> **How to use this doc:** paste it into a new Claude Code chat opened in the
> `prblm-mailer` plugin repo (`prblmcodes/prblm-mailer`). It's a spec + plan, not
> finished decisions. **If anything here is ambiguous or you (the assistant) would
> have to guess — stop and interview me (the maintainer) before writing code.**
> A short list of the decisions most worth confirming is at the end.

---

## 1. Context

`prblm-mailer` is a pip-installable Wagtail newsletter plugin (built on
`django-newsletter`). It has an **Import subscribers** button on the Subscribers
listing in the Wagtail admin, plus a `manage.py import_subscribers` management
command. Both funnel through one function so the rules (especially consent) live
in one place.

- Import/export logic: `prblm_mailer/csv_io.py`
- Admin upload view: `prblm_mailer/admin_views.py` (`import_subscribers` view)
- Management command: `prblm_mailer/management/commands/import_subscribers.py`
- Upload template: `prblm_mailer/templates/prblm_mailer/import_subscribers.html`

Current pinned release: **v0.3.0b1**.

---

## 2. The problem (why this is an issue)

**The importer only accepts a column literally named `email`.** Real subscriber
exports come from anywhere (Mailchimp, MailPoet, Brevo, a CRM, a spreadsheet) and
name that column all sorts of things — `Subscriber`, `Email Address`, `EMAIL`,
`e-mail`, etc. When the header doesn't match, **every row is silently skipped and
nothing is imported**, with no obvious reason why.

### The exact current behaviour (`prblm_mailer/csv_io.py`, `import_rows`)

```python
for raw_row in csv.DictReader(lines):
    row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
    email = row.get("email", "")          # <-- hard-coded header name "email"
    if not _EMAIL_RE.match(email):
        skipped += 1
        if email:
            bad_emails.append(email)       # empty "email" cell → not even flagged as bad
        continue
    name   = row.get("name", "")
    groups = parse_groups(row.get("groups", ""))
    ...
```

Expected headers today: `email, name, status, groups, subscribe_date, create_date`
(`EXPORT_HEADER`). Only `email` (required), `name` (optional), `groups` (optional)
are actually used on import; `status`/dates are ignored.

### Real-world failing case that prompted this

A 686-row export with this header imported **0** subscribers:

```
Subscriber,Sent,Opens,Clicks,Subscribed,Location
claire.reed@essex.gov.uk,0,0,0,"2025-09-17 07:16:57",
sarah@srowell.co.uk,0,0,0,"2025-09-09 08:37:48",
...
```

The email is under **`Subscriber`**, so `row.get("email")` was empty for all 686
rows → all skipped → nothing shown in the Subscribers list, and the only signal
was a success banner reading "0 new, 686 skipped" (easy to miss).

### Why "0 skipped is confusing" matters

Because the missing cell is empty (not an invalid-but-present address), the rows
aren't even added to `bad_emails`, so the admin gets no hint about *which* column
should have been the email. The failure is effectively silent.

---

## 3. Goal

Make the importer handle a CSV **from anywhere** reliably:

1. Correctly find the email column regardless of its header name.
2. Let the user **see and correct** the column mapping before committing.
3. Never fail silently — always show what was detected, imported, and skipped.
4. Stay **backward compatible**: a file exported by this plugin (header
   `email,name,status,groups,…`) must still import unchanged.
5. Keep the **consent model** exactly as it is (rows land *pending* unless the
   uploader ticks "confirmed"; no opt-in emails are ever sent on import).

---

## 4. Recommended solution — Hybrid (auto-detect + confirmable mapping)

This is what mature tools (Mailchimp, Brevo, HubSpot) do, and it's the only
approach that is robust to *any* input:

> **Auto-detect the mapping, then show it to the user to confirm or override.**

Deliver it in **two phases** so Phase 1 ships value fast and Phase 2 adds full
robustness.

### Phase 1 — smart detection in `import_rows` (quick win, backward compatible)

Make `import_rows` figure out the columns itself when no explicit mapping is
given. ~Small change, mostly in `csv_io.py`.

- **Email column resolution, in priority order:**
  1. Header alias match (case-insensitive, trimmed), e.g.
     `email, e-mail, email address, emailaddress, mail, e_mail, subscriber,
     subscriber email, address`.
  2. If no alias matches, **sniff by value**: sample the first ~20 data rows and
     pick the column whose cells most often match `_EMAIL_RE` (require a strong
     majority, e.g. ≥ 70%, to avoid false positives).
  3. If still nothing, raise a clear error ("couldn't find an email column — the
     headers were: …") instead of skipping everything.
- **Name column:** aliases `name, full name, full_name`; optionally combine
  `first name` + `last name` into one name when both are present.
- **Groups column:** aliases `groups, tags, interests` (keeps the existing
  `Group: Value; Group2: Value2` parsing).
- **Delimiter + encoding robustness:** sniff the delimiter with
  `csv.Sniffer().sniff(sample, delimiters=",;\t|")` (handles comma / semicolon /
  tab / pipe exports). Keep the existing UTF-8 BOM handling (`utf-8-sig`).
- **Reporting:** return/surface what was chosen, e.g. *"Using column 'Subscriber'
  as the email address."* Never silent.

Keep `email` as the **top-priority alias** so exported files round-trip exactly.

**Phase 1 acceptance criteria**

- The 686-row `Subscriber,…` file imports all valid rows.
- A plugin-exported `email,name,status,groups,…` file still imports unchanged.
- A semicolon-delimited export works.
- A file with no usable email column fails with a clear message (not a silent 0).

### Phase 2 — column-mapping UI (full robustness)

Turn the admin import into a confirmable two-step flow.

1. **Upload** → parse the header + first ~5 sample rows.
2. **Map** → render a small form: `Email column → [dropdown of the file's
   headers]`, `Name → [dropdown]`, `Groups → [dropdown]`, each **pre-selected by
   the Phase-1 auto-detect**. Show the sample rows as a preview and a **dry-run
   count** ("≈ 681 to import, 5 invalid").
3. **Confirm** → import with the chosen mapping.

Implementation notes:

- Don't stash the whole file in the session. Write the upload to a **temp file
  keyed by a token** (or re-POST the file on confirm), then pass the chosen
  mapping into `import_rows(..., mapping={"email": "Subscriber", "name": None,
  "groups": None})`.
- `import_rows` stays the single source of truth: the mapping just tells it which
  header is which. When `mapping` is omitted it falls back to Phase-1 auto-detect
  (so the management command and API callers keep working with zero args).
- Handle **headerless files**: use `csv.Sniffer().has_header()`; if false, let the
  user pick "column 1 is the email" (or value-sniff).

**Phase 2 acceptance criteria**

- Any CSV can be imported by pointing the dropdowns at the right columns.
- The preview shows real sample values and an accurate dry-run count.
- Overriding a wrong auto-detection works.
- A headerless CSV can still be imported.

### Cross-cutting (both phases)

- **De-dupe within the file** (same email twice) and normalise (trim, lowercase
  the email).
- **Explicit skip report**: "N imported, N updated, N skipped — first 10 invalid:
  …". No silent zero.
- **Consent unchanged**: still default to *pending*, keep the "they already
  consented / confirmed" checkbox, never send opt-in email on import.
- **Backward compatible**: `EXPORT_HEADER` round-trips; existing callers of
  `import_rows(lines, newsletter, confirmed=…)` keep working.

---

## 5. Touch points (files to change in the plugin)

- `prblm_mailer/csv_io.py` — add column detection + make `import_rows` accept an
  optional `mapping`; add a `detect_columns(sample_rows, headers)` helper.
- `prblm_mailer/admin_views.py` — the `import_subscribers` view becomes the
  two-step upload → map → confirm flow.
- `prblm_mailer/templates/prblm_mailer/import_subscribers.html` — add the mapping
  form + sample preview + dry-run count.
- `prblm_mailer/management/commands/import_subscribers.py` — optional parity:
  add a `--map email=Subscriber --map name="Full Name"` style option; default to
  auto-detect.
- Tests: add `tests/` cases (see below).

---

## 6. Testing plan

Add unit tests around `csv_io` with fixture CSVs covering:

- Plugin's own export header (`email,name,status,groups,…`) — round-trips.
- Mailchimp-style (`Email Address,First Name,Last Name,…`).
- The real failing case (`Subscriber,Sent,Opens,Clicks,Subscribed,Location`).
- Semicolon-delimited and tab-delimited variants.
- Headerless file (emails in column 1).
- A file with **no** email column anywhere → clear error, no silent skip.
- Mixed valid/invalid rows → correct created/updated/skipped counts + bad list.
- Dedupe (same email twice) and case/whitespace normalisation.

---

## 7. Release / rollout

- This is a **plugin-repo change**. Implement here, add tests, then cut a new
  tag (suggest **`v0.4.0b1`** — new feature, still beta).
- In each consuming site (e.g. the Be More site) bump the pin in
  `requirements.txt`:
  `prblm-mailer @ git+https://github.com/prblmcodes/prblm-mailer.git@v0.4.0b1`
  then `pip install -r requirements.txt` on every environment (local + servers).
- Update the plugin README / CHANGELOG with the new import behaviour.

---

## 8. Non-goals

- Changing the consent model or sending opt-in emails on import.
- Importing engagement stats (sent/opens/clicks) or subscribe dates — the
  importer sets email/name/groups only. (Could be a separate future ask.)
- A full background-job importer for huge files — fine to do synchronously for
  now; revisit only if files get very large.

---

## 9. Decisions worth confirming with me before coding (interview me if unsure)

1. **Phase scope:** ship Phase 1 (auto-detect) first as its own release, then
   Phase 2 (mapping UI)? Or do both in one release? (Default: Phase 1 first.)
2. **Auto-detect aggressiveness:** is value-sniffing (pick the column that looks
   like emails) acceptable, or should detection be header-alias-only to avoid
   surprises? (Default: aliases first, value-sniff as fallback.)
3. **Name handling:** combine `First Name` + `Last Name` into `name`? (Default:
   yes, when both columns exist.)
4. **Dates:** keep ignoring `subscribe_date`/`create_date` on import, or start
   honouring them when a column maps to them? (Default: keep ignoring.)
5. **Version number** for the release (default `v0.4.0b1`).
6. **Management-command parity:** add the `--map` option now, or UI-only for now?
   (Default: add it for parity.)

If any of the above isn't obvious from the repo, ask me rather than guessing.
