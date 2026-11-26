# Writing and sending newsletters

Newsletters live under **Newsletters** in the Wagtail admin menu. Each one is a subject line
plus a body built from email blocks. A newsletter is not a page — it has no URL on your site.

- [The workflow](#the-workflow)
- [The blocks](#the-blocks)
- [Images](#images)
- [Choosing who gets it](#choosing-who-gets-it)
- [After sending](#after-sending)

---

## The workflow

1. **Newsletters → Add.** Write a subject and build the body from blocks.
2. Press **Save & send** (in the save menu). The **Send page** opens:
   - a **live preview** of the email exactly as it will be sent;
   - **Send a test** — to one address you type; needs no subscribers;
   - **Who gets it** — everyone, or chosen groups.
3. **Proceed to send →** opens a confirmation page showing exactly how many subscribers it will
   go to. **Send now** sends it.

Where a test or a send actually goes depends on the `DELIVERY` setting — the terminal, a local
inbox, or real email. See [Delivery modes](delivery-and-mailgun.md). The admin message after a
send tells you which mode was used, so a dry run never looks like a real send.

Only **confirmed** subscribers receive a newsletter. People who haven't clicked their
confirmation link, or who unsubscribed, are never included, whatever groups you pick.

## The blocks

| Block | Use it for |
|---|---|
| **Header** | A logo and/or a line of text at the top. Either can link. |
| **Content section** | A heading, rich text and an optional button. The workhorse block. |
| **Two columns (image + text)** | An image in one column; heading, text and button in the other. |
| **Two columns (text + text)** | Two text cards side by side, each with its own background, text colour and button. |
| **Image** | One image, with width (25%–full) and alignment, optionally linked. |
| **Two images** | Two images side by side with an adjustable split and optional captions. |
| **Social links** | Icons for your profiles, in a row or stacked, with optional handles. |
| **Spacer / divider** | Vertical space, optionally with a horizontal line. |
| **Footer (with unsubscribe)** | The unsubscribe button, plus an optional logo and text. |

**Always end with a Footer** that has *Show the unsubscribe button* ticked. Each recipient's
button carries their own unsubscribe link. Mail clients also get a one-click unsubscribe header
automatically, whatever the body contains.

### Colours

Section blocks take **one or two background colours** — two make a gradient — and a light or
dark text colour. Outlook desktop can't show CSS gradients, so a two-colour section shows the
first colour there. Buttons default to your `BRAND_COLOR` and can be overridden per block.

Rich text supports headings (H2, H3), bold, italic, lists, horizontal rules and links.

### Social links

Pick a platform, paste the profile URL, and optionally add a handle to show beside the icon
(`@yourname`). The **Email** and **Website** entries also accept `mailto:` and `tel:` links.

- **Colour comes from the chip** — the circle or rounded square behind each icon. Leave *Icon
  colour* blank and each platform uses its own brand colour; set it and every icon matches.
  The icon itself turns white or dark automatically for contrast.
- **Plain icons (no chip) are white or dark only**, following the section's text colour. The
  icons are PNG images, because Gmail strips SVG, and a PNG's colour is fixed.
- **The icons are static files.** Email needs an absolute URL to fetch them, so they appear
  once `WAGTAILADMIN_BASE_URL` points at a server that serves `/static/` publicly — run
  `collectstatic` before your first real send. On `localhost` they show in a local inbox but
  not in a mail client on another machine.

### Two columns and two images

On phones, columns stack vertically. In **Two images**, every split adds up to 100% and the gap
is taken out of the columns, so a row never overflows. Each caption sits under its own image.
**Two columns (text + text)** lets you align both cards to the top, middle or bottom, and
choose rounded or square corners.

## Images

Images come from your Wagtail image library. Each block resizes them for email automatically.

- **Format:** JPEG, PNG and GIF are sent as uploaded. **WebP and AVIF are converted to PNG**,
  because Outlook and some other clients can't display them. (Wagtail 7 and earlier converted
  these itself; from Wagtail 8 the plugin does it.)
- **Image addresses are absolute**, built from `WAGTAILADMIN_BASE_URL`. If an image is blank
  in the preview, that setting doesn't match how you opened the site, or your dev server isn't
  serving `/media/`.

## Choosing who gets it

Under **Who gets it** on the Send page:

- **Tick nothing** — the whole list (every confirmed subscriber).
- **Tick one or more groups** — anyone in *any* of the ticked groups.
- **Subscribers with no group** — adds people who have no group at all.

**Proceed to send** then shows the exact number of recipients for that choice, before anything
is sent.
Groups come from your signup forms or a CSV import — see
[Signup forms and groups](signup-forms.md#groups).

## After sending

A sent newsletter is **locked**: it records what was sent, when, and to how many people, and it
can't be sent again. To send something similar, use **Duplicate** on its Send page; you get a
fresh draft to edit.

With `DELIVERY = "mailgun"` and tracking set up, the newsletter list shows **Opens** and
**Clicks** columns, and the Send page of a sent newsletter shows an **Engagement** panel — see
[Open and click tracking](tracking.md).
