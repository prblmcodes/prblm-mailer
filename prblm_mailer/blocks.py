"""Email-safe StreamField blocks for a newsletter body.

Each block renders a small **MJML** fragment — `sending.render_email_html` stitches
them together and `mrml` compiles the result into the table-based, inline-styled
HTML email clients need. This is why we don't reuse the site's web (Tailwind) blocks.

Backgrounds are inline: one colour = a plain fill, two = a gradient (direction per
block), none = white. Inline (not a head `<style>`) so gradients survive in Gmail/
Apple/iOS. Outlook desktop can't render CSS gradients — a two-colour section shows
white there; single colours work everywhere.

Field layout (rows/widths) is done with `form_classname` + CSS in wagtail_hooks.py.
"""
from django import forms
from django.core.exceptions import ValidationError
from wagtail import blocks
from wagtail.blocks import StructBlockValidationError
from wagtail.images.blocks import ImageChooserBlock

from . import social

RICH_FEATURES = ["h2", "h3", "bold", "italic", "ol", "ul", "hr", "link"]

ALIGN_CHOICES = [("left", "Left"), ("center", "Center"), ("right", "Right")]
TEXT_COLOR_CHOICES = [("dark", "Dark (near-black)"), ("light", "Light (white)")]
SIDE_CHOICES = [("left", "Image left"), ("right", "Image right")]
WIDTH_CHOICES = [
    ("25", "25%"), ("33", "33%"), ("40", "40%"), ("50", "50%"), ("60", "60%"),
    ("66", "66%"), ("75", "75%"), ("80", "80%"), ("100", "Full width"),
]
# Header image sizes (px). Capped so a header logo can't blow up the layout.
IMG_SIZE_CHOICES = [("40", "40px"), ("50", "50px"), ("60", "60px"), ("80", "80px"),
                    ("100", "100px"), ("120", "120px"), ("150", "150px"),
                    ("180", "180px"), ("220", "220px")]

def _brand():
    """The brand colour used for default buttons — a package setting."""
    from .conf import get_setting
    return get_setting("BRAND_COLOR")


def _contrast_text(hex_color):
    """Readable text colour (near-black or white) for a given background hex."""
    try:
        h = (hex_color or "").lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#1f2124" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"
    except Exception:  # noqa: BLE001
        return "#ffffff"


class ColorBlock(blocks.FieldBlock):
    """An optional colour; blank = no colour.

    A plain TextInput (so Wagtail's client-side StreamField renderer is happy)
    carrying a marker class; color_picker.js injects a swatch beside it — a real
    picker that can still be cleared for "none".
    """

    def __init__(self, required=False, help_text="Pick a colour, or clear for none", **kwargs):
        self.field = forms.CharField(
            required=required, max_length=7, help_text=help_text,
            widget=forms.TextInput(attrs={
                "class": "prblm-mailer-color-input", "placeholder": "blank = none",
                "maxlength": 7, "size": 9,
            }),
        )
        super().__init__(**kwargs)


def _c1():
    return ColorBlock(label="Background colour 1")


def _c2():
    return ColorBlock(label="Background colour 2 (makes a gradient)")


def _tc():
    return blocks.ChoiceBlock(choices=TEXT_COLOR_CHOICES, default="dark", label="Text colour")


class _StyledSection(blocks.StructBlock):
    """Resolves editable colours into inline styles for the template:
    `bg` (solid, gradient or white), plus text/button colours with auto-contrast."""

    gradient_dir = "to right"

    class Meta:
        abstract = True

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        light = value.get("text_color") == "light"
        context["text_hex"] = "#ffffff" if light else "#1f2124"
        context["muted_hex"] = "#f0f0f0" if light else "#414141"

        c1 = (value.get("color1") or "").strip()
        c2 = (value.get("color2") or "").strip()
        if c1 and c2:
            context["bg"] = f"linear-gradient({self.gradient_dir}, {c1}, {c2})"
        elif c1:
            context["bg"] = c1
        else:
            context["bg"] = "#ffffff"
        # Solid fallback for Outlook (which ignores gradients) and non-CSS clients.
        context["bg_fallback"] = c1 or "#ffffff"

        button_bg = (value.get("button_color") or "").strip() or _brand()
        context["button_bg"] = button_bg
        context["button_text_hex"] = _contrast_text(button_bg)
        return context


class HeaderBlock(_StyledSection):
    """Reusable header — an optional (linkable) image and/or text; at least one.
    One item centers; with both, choose which side the image sits on."""

    image = ImageChooserBlock(required=False)
    image_link = blocks.URLBlock(required=False, label="Image links to")
    text = blocks.CharBlock(required=False, label="Text")
    text_link = blocks.URLBlock(required=False, label="Text links to")
    color1 = _c1()
    color2 = _c2()
    image_width = blocks.ChoiceBlock(choices=IMG_SIZE_CHOICES, default="150", label="Image size")
    image_side = blocks.ChoiceBlock(choices=SIDE_CHOICES, default="left", label="When both: image on")
    text_color = _tc()

    def clean(self, value):
        result = super().clean(value)
        if not value.get("image") and not value.get("text"):
            raise StructBlockValidationError(block_errors={
                "text": ValidationError("Add an image or some text (at least one)."),
            })
        return result

    class Meta:
        icon = "title"
        label = "Header"
        template = "prblm_mailer/blocks/email_header.html"
        form_classname = "struct-block hdr-fields"


class FooterBlock(_StyledSection):
    """Reusable footer — always shows the Unsubscribe button, plus an optional
    (linkable) image and/or text. Unsubscribe-only centers; one extra pushes
    Unsubscribe right; both extras space out across the row."""

    image = ImageChooserBlock(required=False)
    image_link = blocks.URLBlock(required=False, label="Image links to")
    text = blocks.CharBlock(required=False, label="Text")
    text_link = blocks.URLBlock(required=False, label="Text links to")
    color1 = _c1()
    color2 = _c2()
    image_width = blocks.ChoiceBlock(choices=IMG_SIZE_CHOICES, default="60", label="Image size")
    image_side = blocks.ChoiceBlock(choices=SIDE_CHOICES, default="left", label="When both: image on")
    text_color = _tc()
    show_unsubscribe = blocks.BooleanBlock(
        required=False, default=True, label="Show the unsubscribe button",
    )

    class Meta:
        icon = "form"
        label = "Footer (with unsubscribe)"
        template = "prblm_mailer/blocks/email_footer.html"
        form_classname = "struct-block ftr-fields"


TEXT_WIDTH = {"full": "100%", "wide": "560px", "medium": "440px", "narrow": "340px"}


class ContentBlock(_StyledSection):
    """A content section — heading, description and an optional button. Background:
    none = white, one colour = plain, two = gradient (top-left → bottom-right).
    The button can be a gradient too, and the description width is adjustable."""

    gradient_dir = "to bottom right"

    heading = blocks.CharBlock(required=False, label="Heading")
    description = blocks.RichTextBlock(features=RICH_FEATURES, required=False, label="Description")
    text_width = blocks.ChoiceBlock(
        choices=[("full", "Full"), ("wide", "Wide"), ("medium", "Medium"), ("narrow", "Narrow")],
        default="full", label="Text width", help_text="Narrows the description text only.",
    )
    align = blocks.ChoiceBlock(choices=ALIGN_CHOICES, default="left", label="Align")
    button_text = blocks.CharBlock(required=False, label="Button label")
    button_url = blocks.URLBlock(required=False, label="Button links to")
    button_color1 = ColorBlock(label="Button colour 1")
    button_color2 = ColorBlock(label="Button colour 2 (gradient)")
    button_text_color = ColorBlock(label="Button text colour")
    text_color = _tc()
    color1 = _c1()
    color2 = _c2()

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        b1 = (value.get("button_color1") or "").strip()
        b2 = (value.get("button_color2") or "").strip()
        context["button_bg"] = f"linear-gradient(to right, {b1}, {b2})" if (b1 and b2) else (b1 or _brand())
        context["button_bg_fallback"] = b1 or _brand()
        btc = (value.get("button_text_color") or "").strip()
        context["button_text_hex"] = btc or _contrast_text(b1 or _brand())
        context["text_max_width"] = TEXT_WIDTH.get(value.get("text_width"), "100%")
        return context

    class Meta:
        icon = "doc-full"
        label = "Content section"
        template = "prblm_mailer/blocks/email_content.html"
        form_classname = "struct-block content-fields"


class TwoColumnBlock(_StyledSection):
    """Two columns: an image that fills its column (cover, centered) and a text
    column (heading, description, button). Choose the image side. Background:
    one colour = plain, two = gradient (bottom-left → top-right)."""

    gradient_dir = "to top right"

    image = ImageChooserBlock(label="Column image")
    heading = blocks.CharBlock(required=False, label="Heading")
    description = blocks.RichTextBlock(features=RICH_FEATURES, required=False, label="Description")
    button_text = blocks.CharBlock(required=False, label="Button label")
    button_url = blocks.URLBlock(required=False, label="Button links to")
    button_color1 = ColorBlock(label="Button colour 1")
    button_color2 = ColorBlock(label="Button colour 2 (gradient)")
    text_color = blocks.ChoiceBlock(
        choices=TEXT_COLOR_CHOICES, default="dark", label="Text colour",
        help_text="Use Light on dark backgrounds.",
    )
    button_text_color = ColorBlock(label="Button text colour")
    align = blocks.ChoiceBlock(choices=ALIGN_CHOICES, default="left", label="Align")
    image_side = blocks.ChoiceBlock(choices=SIDE_CHOICES, default="left", label="Image on")
    color1 = _c1()
    color2 = _c2()

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        b1 = (value.get("button_color1") or "").strip()
        b2 = (value.get("button_color2") or "").strip()
        if b1 and b2:
            context["button_bg"] = f"linear-gradient(to right, {b1}, {b2})"
        else:
            context["button_bg"] = b1 or _brand()
        context["button_bg_fallback"] = b1 or _brand()
        # Custom button text colour, or auto-contrast against the button colour.
        btc = (value.get("button_text_color") or "").strip()
        context["button_text_hex"] = btc or _contrast_text(b1 or _brand())
        return context

    class Meta:
        icon = "image"
        label = "Two columns (image + text)"
        template = "prblm_mailer/blocks/email_two_column.html"
        form_classname = "struct-block twocol-fields"


class ImageBlock(blocks.StructBlock):
    """A single image — pick its width and alignment. Full width = edge-to-edge."""

    image = ImageChooserBlock()
    link = blocks.URLBlock(required=False, label="Links to")
    width = blocks.ChoiceBlock(choices=WIDTH_CHOICES, default="100", label="Width")
    align = blocks.ChoiceBlock(choices=ALIGN_CHOICES, default="center", label="Alignment")

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        pct = int(value.get("width") or 100)
        context["full"] = pct >= 100
        # Usable content width ≈ 632px (680px body − 24px padding each side).
        context["img_width_px"] = "" if pct >= 100 else f"{round(632 * pct / 100)}px"
        return context

    class Meta:
        icon = "image"
        label = "Image"
        template = "prblm_mailer/blocks/email_image.html"
        form_classname = "struct-block img-fields"


# A grey that actually reads against white. The old #eeeeee was invisible.
DIVIDER_DEFAULT = "#cccccc"


class SpacerBlock(blocks.StructBlock):
    """Vertical space — optionally with a divider line through the middle."""

    height = blocks.ChoiceBlock(
        choices=[("16", "Small"), ("32", "Medium"), ("56", "Large"), ("80", "Extra large")],
        default="32", label="Height",
    )
    divider = blocks.BooleanBlock(required=False, label="Show a divider line")
    line_color = ColorBlock(
        label="Line colour",
        help_text=f"Blank = grey ({DIVIDER_DEFAULT}). Pick a darker colour to make it stand out.",
    )
    line_width = blocks.ChoiceBlock(
        choices=[("1", "Hairline (1px)"), ("2", "Thin (2px)"), ("3", "Medium (3px)"),
                 ("5", "Thick (5px)")],
        default="1", label="Line thickness",
    )

    def get_context(self, value, parent_context=None):
        # Fall back explicitly: a block saved before these fields existed has no
        # value for them at all, and a ChoiceBlock's default only applies to new
        # blocks — so `value.get(...)` comes back empty for every existing spacer.
        context = super().get_context(value, parent_context)
        context["line_hex"] = (value.get("line_color") or "").strip() or DIVIDER_DEFAULT
        context["line_px"] = (value.get("line_width") or "").strip() or "1"
        return context

    class Meta:
        icon = "minus"
        label = "Spacer / divider"
        template = "prblm_mailer/blocks/email_spacer.html"
        form_classname = "struct-block spacer-fields"


# --------------------------------------------------------------- social links

SOCIAL_LAYOUT_CHOICES = [("row", "One row"), ("column", "One per line")]
SOCIAL_SHAPE_CHOICES = [
    ("circle", "Circle"), ("rounded", "Rounded square"), ("plain", "Plain icon (no chip)"),
]
SOCIAL_SIZE_CHOICES = [("32", "Small"), ("40", "Medium"), ("48", "Large")]
# A profile link isn't always http: Email and WhatsApp entries want mailto:/tel:,
# which a URLBlock rejects outright — hence a CharBlock and this check.
LINK_SCHEMES = ("http://", "https://", "mailto:", "tel:")


def _icon_url(slug, variant):
    """Absolute URL of one shipped icon PNG.

    Absolute because a mail client has no site to resolve `/static/...` against.
    Returns "" rather than raising if the file isn't collected: a missing icon
    should cost you an icon, not the whole send.
    """
    from django.templatetags.static import static

    try:
        path = static(f"prblm_mailer/icons/{slug}-{variant}.png")
    except Exception:  # noqa: BLE001
        return ""
    if path.startswith(("http://", "https://", "//")):
        return path                      # already absolute (S3/CDN storage)
    # Local import: sending imports models, which imports this module.
    from .sending import absolute_url

    return absolute_url(path)


class SocialLinkBlock(blocks.StructBlock):
    """One profile: which platform, where it goes, and an optional handle."""

    platform = blocks.ChoiceBlock(choices=social.platform_choices, label="Platform")
    url = blocks.CharBlock(label="Links to", help_text="https://… (or mailto:… / tel:…)")
    username = blocks.CharBlock(
        required=False, label="Handle",
        help_text="Optional, shown next to the icon — e.g. @yourname",
    )

    def clean(self, value):
        result = super().clean(value)
        url = (value.get("url") or "").strip()
        if url and not url.lower().startswith(LINK_SCHEMES):
            raise StructBlockValidationError(block_errors={
                "url": ValidationError("Start the link with https://, mailto: or tel:."),
            })
        return result

    class Meta:
        icon = "link"
        label = "Social link"
        form_classname = "struct-block social-link-fields"


class SocialLinksBlock(_StyledSection):
    """Social profiles as icons — in a row or stacked, with optional handles.

    The icons are PNGs shipped with the package (email clients strip SVG), in white
    and dark only. Colour comes from the *chip* behind the glyph, which is an inline
    background every client renders, and the glyph flips to whichever of the two
    contrasts with it. A plain icon has no chip, so there it really is white or dark
    — decided by the section's text colour.
    """

    links = blocks.ListBlock(SocialLinkBlock(), label="Profiles", min_num=1)
    layout = blocks.ChoiceBlock(choices=SOCIAL_LAYOUT_CHOICES, default="row", label="Layout")
    align = blocks.ChoiceBlock(choices=ALIGN_CHOICES, default="center", label="Align")
    shape = blocks.ChoiceBlock(choices=SOCIAL_SHAPE_CHOICES, default="circle", label="Icon shape")
    icon_size = blocks.ChoiceBlock(choices=SOCIAL_SIZE_CHOICES, default="40", label="Icon size")
    icon_color = ColorBlock(
        label="Icon colour",
        help_text="Blank = each platform's own brand colour. Ignored by plain icons.",
    )
    text_color = _tc()
    color1 = _c1()
    color2 = _c2()

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        shape = value.get("shape") or "circle"
        size = int(value.get("icon_size") or 40)
        chosen = (value.get("icon_color") or "").strip()
        plain = shape == "plain"

        context["box_px"] = size
        # A plain glyph carries the whole shape, so it needs the room a chip would
        # otherwise take; inside a chip it has to leave a margin or it looks stuffed.
        context["glyph_px"] = round(size * (0.72 if plain else 0.55))
        context["radius"] = "50%" if shape == "circle" else (f"{round(size / 5)}px" if shape == "rounded" else "0")
        context["plain"] = plain

        items = []
        for link in value.get("links") or []:
            slug = link.get("platform") or ""
            label, brand = social.PLATFORMS.get(slug, (slug.title(), _brand()))
            chip = chosen or brand
            if plain:
                variant = "white" if value.get("text_color") == "light" else "dark"
            else:
                variant = "white" if _contrast_text(chip) == "#ffffff" else "dark"
            items.append({
                "url": (link.get("url") or "").strip(),
                "username": (link.get("username") or "").strip(),
                "label": label,
                "chip": chip,
                "icon": _icon_url(slug, variant),
            })
        context["items"] = items
        return context

    class Meta:
        icon = "site"
        label = "Social links"
        template = "prblm_mailer/blocks/email_social.html"
        form_classname = "struct-block social-fields"


# ------------------------------------------------------ two columns of text

GAP_CHOICES = [("0", "None"), ("3", "Small"), ("5", "Medium"), ("8", "Large")]


class _CardBlock(blocks.StructBlock):
    """One side of the text/text block: its own copy, colours and button.

    Per-card colours are the point of this block — two cards on one shared
    background would just be the Content block cut in half.
    """

    heading = blocks.CharBlock(required=False, label="Heading")
    description = blocks.RichTextBlock(features=RICH_FEATURES, required=False, label="Description")
    button_text = blocks.CharBlock(required=False, label="Button label")
    button_url = blocks.URLBlock(required=False, label="Button links to")
    color = ColorBlock(label="Card background")
    text_color = blocks.ChoiceBlock(
        choices=TEXT_COLOR_CHOICES, default="dark", label="Text colour",
        help_text="Use Light on a dark card.",
    )
    button_color = ColorBlock(label="Button colour")
    button_text_color = ColorBlock(label="Button text colour")

    class Meta:
        icon = "doc-full"
        label = "Column"
        form_classname = "struct-block card-fields"


def _card_context(card):
    """Resolve one card's editable colours into the values its template needs."""
    light = card.get("text_color") == "light"
    button_bg = (card.get("button_color") or "").strip() or _brand()
    return {
        "value": card,
        "bg": (card.get("color") or "").strip(),
        "text_hex": "#ffffff" if light else "#1f2124",
        "muted_hex": "#f0f0f0" if light else "#414141",
        "button_bg": button_bg,
        "button_text_hex": (card.get("button_text_color") or "").strip() or _contrast_text(button_bg),
    }


class TwoColumnTextBlock(_StyledSection):
    """Two text columns side by side, each with its own background and button —
    the text/text counterpart to the image/text two-column block."""

    gradient_dir = "to bottom right"

    left = _CardBlock(label="Left column")
    right = _CardBlock(label="Right column")
    align = blocks.ChoiceBlock(choices=ALIGN_CHOICES, default="left", label="Align")
    valign = blocks.ChoiceBlock(
        choices=[("top", "Top"), ("middle", "Middle"), ("bottom", "Bottom")],
        default="top", label="Vertical alignment",
        help_text="How the shorter column sits against the taller one.",
    )
    gap = blocks.ChoiceBlock(choices=GAP_CHOICES, default="5", label="Gap between columns")
    corners = blocks.ChoiceBlock(
        choices=[("10", "Rounded"), ("0", "Square")], default="10", label="Card corners",
    )
    text_color = _tc()
    color1 = _c1()
    color2 = _c2()

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        gap = int(value.get("gap") or 0)
        context["gap_pct"] = gap
        # The gap is a spacer column, so the cards give up its width between them.
        context["card_pct"] = round((100 - gap) / 2, 2)
        context["left"] = _card_context(value.get("left") or {})
        context["right"] = _card_context(value.get("right") or {})
        return context

    class Meta:
        icon = "list-ul"
        label = "Two columns (text + text)"
        template = "prblm_mailer/blocks/email_two_column_text.html"
        form_classname = "struct-block twocoltext-fields"


# ----------------------------------------------------------- two images

# Each pair must total 100: the halves are percentages of the section, and a pair
# summing to 99 leaves a sliver of background down one edge of the row.
SPLIT_CHOICES = [
    ("50-50", "Equal halves"), ("60-40", "Wider left"), ("40-60", "Wider right"),
    ("67-33", "Much wider left"), ("33-67", "Much wider right"),
]


class TwoImageBlock(_StyledSection):
    """Two images side by side, with an adjustable split and optional captions."""

    image_left = ImageChooserBlock(label="Left image")
    link_left = blocks.URLBlock(required=False, label="Left links to")
    caption_left = blocks.CharBlock(required=False, label="Left caption")
    image_right = ImageChooserBlock(label="Right image")
    link_right = blocks.URLBlock(required=False, label="Right links to")
    caption_right = blocks.CharBlock(required=False, label="Right caption")
    split = blocks.ChoiceBlock(choices=SPLIT_CHOICES, default="50-50", label="Split")
    gap = blocks.ChoiceBlock(choices=GAP_CHOICES, default="3", label="Gap between images")
    text_color = _tc()
    color1 = _c1()
    color2 = _c2()

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        gap = int(value.get("gap") or 0)
        left, right = (value.get("split") or "50-50").split("-")
        # Percentages are of the section, so the gap has to come out of the columns
        # rather than be added on top — otherwise the row overflows the body width.
        scale = (100 - gap) / 100
        context["gap_pct"] = gap
        context["left_pct"] = round(int(left) * scale, 2)
        context["right_pct"] = round(int(right) * scale, 2)
        return context

    class Meta:
        icon = "image"
        label = "Two images"
        template = "prblm_mailer/blocks/email_two_image.html"
        form_classname = "struct-block twoimg-fields"


def email_body_blocks():
    """The block set offered in a newsletter's body — email blocks only."""
    return [
        ("header", HeaderBlock()),
        ("content", ContentBlock()),
        ("two_column", TwoColumnBlock()),
        ("two_column_text", TwoColumnTextBlock()),
        ("image", ImageBlock()),
        ("two_image", TwoImageBlock()),
        ("social", SocialLinksBlock()),
        ("spacer", SpacerBlock()),
        ("footer", FooterBlock()),
    ]
