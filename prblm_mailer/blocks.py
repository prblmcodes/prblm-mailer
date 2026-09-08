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


def email_body_blocks():
    """The block set offered in a newsletter's body — email blocks only."""
    return [
        ("header", HeaderBlock()),
        ("content", ContentBlock()),
        ("two_column", TwoColumnBlock()),
        ("image", ImageBlock()),
        ("spacer", SpacerBlock()),
        ("footer", FooterBlock()),
    ]
