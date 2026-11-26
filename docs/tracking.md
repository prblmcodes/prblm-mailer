# Open and click tracking

> **Tracking only works with `DELIVERY = "mailgun"`.** Mailgun counts opens and clicks: it
> rewrites each link and adds an invisible open pixel as it sends, then reports back to your
> site through a webhook. With `dry_run`, `console` or `local`, Mailgun isn't involved, so
> clicking a link in a local inbox records nothing. That's expected. To test the tracking path
> locally, use [`simulate_mailgun_click`](#testing-it-locally).

The plugin runs no tracking redirects or pixels of its own. Everything comes from Mailgun
through the [Anymail](https://anymail.dev) webhook.

## Setting it up

1. In Mailgun, open your sending domain and turn on **click tracking** and **open tracking**.
2. Add webhooks for these events: `clicked`, `opened`, `permanent_fail`, `temporary_fail`,
   `complained` and `unsubscribed`. Point all of them at:

   ```
   https://USER:PASS@your-site.com/anymail/mailgun/tracking/
   ```

   where `USER:PASS` is your `ANYMAIL["WEBHOOK_SECRET"]`.
3. Set `ANYMAIL["MAILGUN_WEBHOOK_SIGNING_KEY"]` to the signing key from Mailgun's webhook page,
   so your site only accepts genuine Mailgun requests.
4. Run `python manage.py mailgun_doctor` to check every step
   ([details](delivery-and-mailgun.md#going-live-with-mailgun)).

The bounce and complaint webhooks also keep your list clean — see
[bounces and complaints](subscribers.md#bounces-complaints-and-unsubscribes).

## What you see

- The **Newsletters** list gets **Clicks** and **Opens** columns.
- A sent newsletter's **Send page** shows an **Engagement** panel: total and unique opens and
  clicks, open and click rates, and the most-clicked links.

What's counted:

- **Test sends are ignored**, so testing never inflates the numbers.
- **Unsubscribe clicks don't count** as engagement.
- **Mailgun's retries are de-duplicated** — each Mailgun event is recorded once, however many
  times it's delivered.

**Open rates are approximate** for every email service, not just this one: some mail apps load
images automatically (counting opens nobody made), and others block images (missing real ones).
Clicks are the more reliable signal.

## Testing it locally

```bash
python manage.py simulate_mailgun_click
```

This posts a realistic, correctly signed Mailgun click event to your own webhook, so the real
signature check, parser and storage all run — no Mailgun account needed. By default it uses
your newest sent newsletter and its first recipient.

| Option | Use |
|---|---|
| `--broadcast ID` | Which newsletter the click belongs to |
| `--subscriber ID` | Which subscriber clicked |
| `--url URL` | The link that was "clicked" |
| `--event-id X` | Run twice with the same value to see the retry de-duplication |
