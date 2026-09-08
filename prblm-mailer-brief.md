# Brief: extract the email platform into `prblm-mailer`

## The goal

Turn the email platform we built inside beMore into an internal package that installs into
any prblm Wagtail site with a few settings entries.

Build the simplest thing that works for two sites. We are not writing a general-purpose
library — no PyPI, no version matrix, no plugin architecture. If we need a feature for a
third site later, we add it later.

## Definition of done

1. `prblm-mailer` is a private repo, pip-installable from git.
2. It's installed and working on the **Breaking Beats staging site**, with its own
   subscriber model — campaign created, subscribers added, send triggered, stats visible.
3. Breaking Beats' settings contain no more than the config block below.
4. `README.md` covers installation and every setting.
5. Tests cover campaign send, subscriber opt-in, and unsubscribe.

Breaking Beats is the proof. A package that only runs in the project it was extracted from
proves nothing, and a real second site is where the assumptions you didn't know you'd made
will surface.

## Explicitly not this week

- **Console output only on Breaking Beats staging.** Staging databases are often clones of
  production. A real Mailgun key plus a real subscriber list plus a test send means real
  email to real people, with no recall. Check what's in that database before configuring
  anything.
- Don't migrate beMore onto the package. Day-one job for when I'm back.
- Don't add features. Spot something missing, write it in `IDEAS.md`, move on.
- Don't rewrite working code because you'd have done it differently. Extract first.
- Don't leave anything on Breaking Beats they didn't ask for — note what needs reverting.

---

## Target settings surface

```python
INSTALLED_APPS = [..., "prblm_mailer"]

PRBLM_MAILER = {
    "SUBSCRIBER_MODEL": "subscribers.Subscriber",
    "FROM_EMAIL": "hello@example.com",
    "MAILGUN_API_KEY": env("MAILGUN_API_KEY"),
    "MAILGUN_DOMAIN": "mg.example.com",
    "DRY_RUN": DEBUG,          # default; logs instead of sending
}
```

```python
path("mailer/", include("prblm_mailer.urls")),
```

Everything else comes from defaults in a settings object inside the package. Pin Wagtail
and Django to exactly the versions we run — supporting a range is work we don't need.

---

## The one abstraction worth building

**The swappable subscriber model.** Every site wants different fields, and this is the
only thing that would genuinely block reuse if we got it wrong.

Follow Django's `AUTH_USER_MODEL` pattern: ship `AbstractSubscriber` with the fields the
platform needs, host project subclasses it, `SUBSCRIBER_MODEL` points at the concrete
model. Resolve it lazily — string references in ForeignKeys, a `get_subscriber_model()`
helper. Never import the model at module level or it explodes on app loading.

Breaking Beats' subscriber model should have at least one field beMore's doesn't, so you
know it actually works.

## Everything else stays concrete

**Sending.** One `prblm_mailer/mailgun.py` module that talks to the Mailgun API. Not a
backend class hierarchy, not a `SEND_BACKEND` setting. We always use Mailgun, always EU,
so hardcode `https://api.eu.mailgun.net/v3` and move on. Wrong region gives you 401s that
look like bad credentials, so it's worth getting right and then never thinking about again.

For dev and staging safety, a single `DRY_RUN` boolean that logs the message instead of
posting it. Defaults to `settings.DEBUG`. That covers the actual need without a swappable
backend.

**Background sending.** Use Django's built-in `django.tasks` — `@task` decorator,
`.enqueue()`. Don't build a task runner abstraction; that's what the framework now
provides. The host project configures `TASKS` and runs whatever worker it likes. Two
constraints that come with it:

- Task arguments must be JSON-serializable. Pass IDs, never model instances. If the
  current code passes objects into Celery tasks, that's a rewrite.
- Enqueue inside `transaction.on_commit()` after a database write, or the worker can pick
  the job up before the row commits.

Django ships the API but no production worker — that's the host project's problem, and one
line in the README.

**Templates and static files.** Namespace under `templates/prblm_mailer/` so host projects
can override individual files. Ship defaults that work with no configuration.

## The beMore fingerprint hunt

The tedious part, and where the bugs are. Hardcoded sender addresses and reply-to, their
tracking domain, brand colours in admin CSS, absolute URLs, StreamField blocks that are
really their content model rather than a general email block, anything touching their
business logic. Each one becomes a setting, becomes an overridable default, or stays
behind in their repo.

## Migrations

beMore hasn't launched, so the hard version of this doesn't apply — no state-only
migrations, no `db_table` juggling. Drop the old tables, run fresh, re-enter anything that
matters.

One check before assuming that: "not launched" isn't "no data". Confirm whether beMore
have been entering content during the build, or whether a subscriber list has been
imported ready for launch. If either is true, tell me before you drop anything.

---

## Shape of the week

- **Mon** — Repo, skeleton, settings object. Get an empty package installing into Breaking
  Beats staging before moving any real code. Plus the two checks below.
- **Tue** — Models. Abstract subscriber, campaign, send log, migrations.
- **Wed** — Mailgun module, `@task` decorators, webhooks.
- **Thu** — Wagtail admin, templates, static files, fingerprint hunt.
- **Fri** — Breaking Beats running end to end, tests, README.

If the week runs tight, cut the tests before you cut the Breaking Beats install.

## Monday morning, before anything else

- **What background queue does beMore run?** Grep `pyproject.toml` / `requirements*.txt`
  for celery, django-q, rq, huey; look for `celery.py`; check the Procfile or systemd units
  for a worker; check docker-compose for Redis or RabbitMQ. Five minutes.
- **Exact Wagtail minor version.** "7.something" isn't precise enough — 7.0 LTS runs on
  Django 4.2/5.1/5.2, 7.4 LTS on 5.2/6.0 only. Determines whether `django.tasks` is native
  or needs the `django-tasks` backport.
- **Does beMore have real data yet?** See migrations above.

Tell me all three in Monday's note.

## Working arrangements

End of day, send me a short note: what you did, what's next, what's blocking. I'll read it
once a day and only reply if something needs a decision. If a decision needs me and I'm
slow, pick the option that's easiest to reverse, note it, and carry on.
