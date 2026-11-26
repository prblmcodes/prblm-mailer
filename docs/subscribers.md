# Managing subscribers

- [The list and groups](#the-list-and-groups)
- [The Subscribers admin](#the-subscribers-admin)
- [Importing a CSV](#importing-a-csv)
- [Exporting](#exporting)
- [Bounces, complaints and unsubscribes](#bounces-complaints-and-unsubscribes)

---

## The list and groups

Your **list** is the django-newsletter `Newsletter` row you created during installation. Its
slug must match `PRBLM_MAILER["NEWSLETTER_SLUG"]` (`"main"` by default). Everyone who signs up
joins that one list, and every newsletter is sent from it.

**Groups** are the layer inside the list. A group tags a subscriber with an answer they gave
(*Instrument: Guitar*), so a newsletter can go to just part of the list.

| | What it is | How many | How someone joins |
|---|---|---|---|
| **List** | The mailing list itself | One, set by `NEWSLETTER_SLUG` | Signs up and confirms |
| **Group** | A tag on a subscriber | As many as your forms or imports create | Answers a grouping field, or comes in through an import |

This split is deliberate: separate lists would mean separate confirmations, separate
unsubscribes and people signing up twice. One list plus groups gives you targeting without any
of that.

## The Subscribers admin

**Subscribers** in the admin menu lists everyone with their name, status (*Confirmed*,
*Pending confirmation* or *Unsubscribed*), groups and subscribe date. You can search it, delete people, and
use **Import CSV** and **Export CSV** in the header.

**There is no Edit button.** A subscriber's status records consent — signed up, confirmed,
unsubscribed — and editing it by hand is how a list ends up mailing someone who never agreed.
People join through a signup form's confirmation email or an import, and leave by unsubscribing
or bouncing.

Deleting a subscriber also removes the IP addresses recorded with their opens and clicks.

## Importing a CSV

**Subscribers → Import CSV.** The importer reads exports from Mailchimp, Brevo, MailPoet, a CRM
or a spreadsheet. The columns don't need any particular names, and it works in two steps so a
wrong guess costs nothing.

1. **Upload.** It finds the email column by its header (`email`, `e-mail`, `Email Address`,
   `Subscriber`, …) or, failing that, by looking at which column actually contains addresses.
   Comma-, semicolon-, tab- and pipe-separated files all work, with or without a header row.
2. **Check and confirm.** You see which column it chose for each field, a few real rows from
   your file, and exactly what will happen — *"680 new, 0 already on the list, 3 skipped (2
   invalid, 1 repeated in the file)"*. Change any column from its dropdown, press **Update
   preview** to recount, then **Import**.

The preview is the real import run without saving anything, so its numbers are the numbers
you get.

### What it reads

| Field | Notes |
|---|---|
| **Email** | Required. Trimmed and lower-cased. |
| **Name**, or **First name** + **Last name** | First and last are joined into one name. |
| **Groups** | Any column — see below. |
| **Status** | Used only to skip people who opted out elsewhere — consent comes from the question below, not from this column. |
| **Subscribe date** | Keeps the date people originally joined. |

Other columns (opens, clicks, tags from another tool) are ignored.

### Consent

The import asks one question — whether you already hold these people's consent:

- **No (the default):** everyone arrives **pending** and receives nothing until they confirm
  for themselves.
- **Yes:** they arrive **confirmed** and will get your next newsletter. Only for a list whose
  consent you actually hold.

**An import never sends confirmation emails.** Mailing a freshly imported list all at once is
the fastest way to get a sending domain blocked.

### What it won't do

- **Re-add people who opted out.** Rows whose status is `unsubscribed`, `cleaned`, `bounced`
  or `complained` are skipped and counted separately.
- **Create duplicates.** An address repeated in the file is imported once, and an existing
  subscriber is matched whatever the capitalisation.
- **Downgrade anyone.** An already-confirmed subscriber stays confirmed.
- **Report a cheerful "0 imported"** when it couldn't find addresses. If no column looks like
  email addresses, it stops and names the headers it saw.

### Groups from a column

Map any column — `Location`, `Membership`, `Interest` — as *Groups*, and the column's **own
name becomes the group**: `Essex` in a `Location` column files that person under
*Location: Essex*.

- Separate several values in one cell with `;` (commas aren't separators, because a value like
  "Leeds, West Yorkshire" contains one).
- Write `Group: Value` in a cell to name the group yourself.
- The preview tells you how many rows actually carry a group, so an empty column says so.

### Subscribe dates

Map the column that holds the date people originally joined, so your list doesn't look like
everyone signed up on the day you migrated.

- ISO dates, `17/09/2025`, `09/17/2025`, `17 Sep 2025`, `Sep 17, 2025` and unix timestamps all
  work.
- Whether slashed dates are day-first or month-first is worked out from the file itself
  (`17/09` can only mean the 17th), and the preview says which reading it used.
- A date it can't read never costs you the subscriber: that row imports without a date, and
  the number of unreadable dates is reported.
- With no date column, **confirmed** imports are dated today and **pending** ones get a date
  when they confirm. An existing date is never overwritten.

### From the command line

The same importer, with the same rules and detection:

```bash
python manage.py import_subscribers list.csv                 # imports as pending
python manage.py import_subscribers list.csv --dry-run       # count it, write nothing
python manage.py import_subscribers list.csv --confirmed     # only if you hold consent
python manage.py import_subscribers list.csv --map email=Subscriber --map name="Full Name"
```

`--map FIELD=COLUMN` names a column explicitly and can be repeated. Fields: `email`, `name`,
`first_name`, `last_name`, `groups`, `status`, `subscribe_date`. `--newsletter SLUG` imports
into a list other than the configured one.

## Exporting

**Subscribers → Export CSV** downloads the whole list with the columns `email`, `name`,
`status` (`confirmed` / `pending` / `unsubscribed`), `groups`, `subscribe_date` and
`create_date`. From the command line:

```bash
python manage.py export_subscribers --output list.csv      # or omit --output for stdout
```

An export imports straight back into another site: groups and dates carry over and
unsubscribed people are skipped. Like any import, people arrive pending unless you import
with consent.

## Bounces, complaints and unsubscribes

With Mailgun's webhooks set up ([tracking](tracking.md#setting-it-up)), the list cleans itself:

- **Hard bounces** (the address doesn't exist), **rejections**, **spam complaints** and
  **unsubscribes reported by Mailgun** mark the subscriber as unsubscribed automatically.
- **Soft bounces** (a full mailbox, a temporary error) are recorded but don't unsubscribe
  anyone.

**Unsubscribing is final** for every future send. Every email carries a personal unsubscribe
link and a one-click unsubscribe header that Gmail and Apple Mail show as a button. Someone
who unsubscribed can come back only by signing up and confirming again.
