"""The email blocks added in 0.3.0: social links, two text columns, two images.

These assert on the *compiled* email HTML rather than the MJML, because the
compilation step is where a mis-nested block shows up (MJML that looks fine can
still be foster-parented out of its section — see email_content.html).
"""
from django.test import TestCase, override_settings

from wagtail.rich_text import RichText   # Wagtail 6 needs a RichText, not a raw str

from prblm_mailer import sending
from prblm_mailer.blocks import SocialLinksBlock, TwoColumnTextBlock, TwoImageBlock
from prblm_mailer.models import Broadcast

MAILER = {"FROM_EMAIL": "hi@x.co", "FROM_NAME": "X", "BRAND_COLOR": "#fd6f29"}


def social(**kw):
    """A social block value, with sensible defaults for anything not overridden.

    Built through `to_python` rather than handed over as a raw dict: on Wagtail 6 a
    plain list stays a plain list instead of becoming a ListValue, and the post-save
    indexer then trips over the missing `bound_blocks`. The database always hands
    these values over via to_python, so this is what real usage looks like anyway.
    """
    data = {
        "links": [{"platform": "instagram", "url": "https://instagram.com/me",
                   "username": "@me"}],
        "layout": "row", "align": "center", "shape": "circle", "icon_size": "40",
        "icon_color": "", "text_color": "dark", "color1": "", "color2": "",
    }
    data.update(kw)
    return SocialLinksBlock().to_python(data)


def card(**kw):
    data = {"heading": "H", "description": RichText("<p>copy</p>"), "button_text": "",
            "button_url": "", "color": "", "text_color": "dark",
            "button_color": "", "button_text_color": ""}
    data.update(kw)
    return data


def render(block_type, value):
    broadcast = Broadcast.objects.create(subject="S", body=[(block_type, value)])
    return sending.render_email_html(broadcast)


@override_settings(PRBLM_MAILER=MAILER, WAGTAILADMIN_BASE_URL="https://example.org")
class SocialLinksTests(TestCase):
    def test_icon_src_is_absolute(self):
        # A mail client has no site to resolve /static/... against.
        html = render("social", social())
        self.assertIn("https://example.org/static/prblm_mailer/icons/instagram-", html)

    def test_chip_defaults_to_each_platform_brand_colour(self):
        html = render("social", social(links=[
            {"platform": "instagram", "url": "https://i.co/me", "username": ""},
            {"platform": "facebook", "url": "https://f.co/me", "username": ""},
        ]))
        self.assertIn("#E4405F", html)      # Instagram
        self.assertIn("#1877F2", html)      # Facebook

    def test_icon_colour_overrides_every_chip(self):
        html = render("social", social(icon_color="#123456", links=[
            {"platform": "instagram", "url": "https://i.co/me", "username": ""},
            {"platform": "facebook", "url": "https://f.co/me", "username": ""},
        ]))
        # Two chips, each carrying the colour twice (bgcolor attribute + inline style).
        self.assertEqual(html.count('bgcolor="#123456"'), 2)
        self.assertNotIn("#E4405F", html)

    def test_glyph_follows_the_chip_for_contrast(self):
        dark = render("social", social(icon_color="#000000"))
        light = render("social", social(icon_color="#ffffff"))
        self.assertIn("instagram-white.png", dark)
        self.assertIn("instagram-dark.png", light)

    def test_plain_icons_follow_the_section_text_colour(self):
        # No chip to contrast against, so the section's light/dark setting decides.
        on_dark = render("social", social(shape="plain", text_color="light"))
        self.assertIn("instagram-white.png", on_dark)
        self.assertNotIn("border-radius:50%", on_dark)

    def test_handle_is_rendered(self):
        self.assertIn("@me", render("social", social()))

    def test_stays_inside_its_section(self):
        # An mj-raw here would be foster-parented above the section, losing the
        # background; the chip must appear after the section's own colour.
        html = render("social", social(color1="#334455"))
        self.assertLess(html.find("#334455"), html.find("instagram-"))

    def test_column_layout_renders_each_profile(self):
        html = render("social", social(layout="column", links=[
            {"platform": "instagram", "url": "https://i.co/me", "username": "@a"},
            {"platform": "github", "url": "https://g.co/me", "username": "@b"},
        ]))
        self.assertIn("@a", html)
        self.assertIn("@b", html)

    def test_mailto_and_tel_links_are_allowed(self):
        block = SocialLinksBlock()
        for url in ("mailto:hi@x.co", "tel:+441234", "https://x.co"):
            with self.subTest(url=url):
                block.child_blocks["links"].child_block.clean(
                    {"platform": "email", "url": url, "username": ""})

    def test_a_link_without_a_scheme_is_rejected(self):
        from wagtail.blocks import StructBlockValidationError

        block = SocialLinksBlock().child_blocks["links"].child_block
        with self.assertRaises(StructBlockValidationError):
            block.clean({"platform": "facebook", "url": "facebook.com/me", "username": ""})

    def test_an_unknown_platform_does_not_break_the_render(self):
        # A slug saved before an icon existed must degrade, not explode mid-send.
        html = render("social", social(links=[
            {"platform": "myspace", "url": "https://my.co/me", "username": "@me"}]))
        self.assertIn("@me", html)


@override_settings(PRBLM_MAILER=MAILER, WAGTAILADMIN_BASE_URL="https://example.org")
class TwoColumnTextTests(TestCase):
    def value(self, **kw):
        data = {"left": card(heading="Left"), "right": card(heading="Right"),
                "align": "left", "valign": "top", "gap": "5", "corners": "10",
                "text_color": "dark", "color1": "", "color2": ""}
        data.update(kw)
        return data

    def test_each_column_keeps_its_own_background(self):
        html = render("two_column_text", self.value(
            left=card(heading="Left", color="#112233", text_color="light"),
            right=card(heading="Right", color="#ffeedd")))
        self.assertIn("#112233", html)
        self.assertIn("#ffeedd", html)

    def test_each_column_keeps_its_own_button(self):
        html = render("two_column_text", self.value(
            left=card(button_text="Go left", button_url="https://a.co", button_color="#ffcc00"),
            right=card(button_text="Go right", button_url="https://b.co", button_color="#00ccff")))
        self.assertIn("Go left", html)
        self.assertIn("Go right", html)
        self.assertIn("#ffcc00", html)
        self.assertIn("#00ccff", html)

    def test_button_text_contrasts_with_its_own_button(self):
        html = render("two_column_text", self.value(
            left=card(button_text="B", button_url="https://a.co", button_color="#ffffff")))
        self.assertIn("color:#1f2124", html)      # dark text on a white button

    def test_the_gap_comes_out_of_the_columns(self):
        # Otherwise the row totals more than 100% and overflows the body width.
        context = TwoColumnTextBlock().get_context(
            TwoColumnTextBlock().to_python(self.value(gap="8")))
        self.assertEqual(context["gap_pct"], 8)
        self.assertEqual(context["card_pct"] * 2 + context["gap_pct"], 100)

    def test_no_gap_drops_the_spacer_column(self):
        context = TwoColumnTextBlock().get_context(
            TwoColumnTextBlock().to_python(self.value(gap="0")))
        self.assertEqual(context["card_pct"], 50)

    def test_vertical_alignment_is_applied(self):
        # MJML repeats the alignment on several elements per column, so assert it is
        # there at all rather than counting.
        for choice in ("middle", "bottom"):
            with self.subTest(choice=choice):
                html = render("two_column_text", self.value(valign=choice))
                self.assertIn(f"vertical-align:{choice}", html)

    def test_vertical_alignment_defaults_to_top(self):
        # A card saved before the field existed has no value for it at all, and a
        # ChoiceBlock default only applies to new blocks.
        value = self.value()
        del value["valign"]
        html = render("two_column_text", value)
        self.assertNotIn("vertical-align:middle", html)
        self.assertNotIn("vertical-align:bottom", html)

    def test_square_corners_are_respected(self):
        html = render("two_column_text", self.value(
            corners="0", left=card(color="#112233"), right=card(color="#ffeedd")))
        self.assertNotIn("border-radius:10px", html)


@override_settings(PRBLM_MAILER=MAILER, WAGTAILADMIN_BASE_URL="https://example.org")
class TwoImageTests(TestCase):
    def setUp(self):
        from io import BytesIO

        from django.core.files.images import ImageFile
        from wagtail.images import get_image_model

        def an_image(name):
            from PIL import Image

            buf = BytesIO()
            Image.new("RGB", (800, 600), "red").save(buf, "PNG")
            buf.seek(0)
            return get_image_model().objects.create(
                title=name, file=ImageFile(buf, name=f"{name}.png"))

        self.left, self.right = an_image("left"), an_image("right")

    def value(self, **kw):
        data = {"image_left": self.left, "link_left": "", "caption_left": "",
                "image_right": self.right, "link_right": "", "caption_right": "",
                "split": "50-50", "gap": "3",
                "text_color": "dark", "color1": "", "color2": ""}
        data.update(kw)
        return data

    def stored(self, **kw):
        """The same value in its *stored* form — images as pks, which is what
        `to_python` expects (a live render gets the instances instead)."""
        data = self.value(**kw)
        data["image_left"], data["image_right"] = self.left.pk, self.right.pk
        return data

    def test_both_images_render(self):
        html = render("two_image", self.value())
        self.assertEqual(html.count("<img"), 2)

    def test_captions_render_under_their_own_image(self):
        html = render("two_image", self.value(caption_left="Left cap", caption_right="Right cap"))
        self.assertIn("Left cap", html)
        self.assertIn("Right cap", html)

    def test_links_are_applied_per_image(self):
        html = render("two_image", self.value(link_left="https://a.co", link_right="https://b.co"))
        self.assertIn("https://a.co", html)
        self.assertIn("https://b.co", html)

    def test_split_and_gap_always_total_one_hundred(self):
        block = TwoImageBlock()
        for split in ("50-50", "60-40", "40-60", "67-33", "33-67"):
            for gap in ("0", "3", "5", "8"):
                with self.subTest(split=split, gap=gap):
                    context = block.get_context(block.to_python(self.stored(split=split, gap=gap)))
                    total = context["left_pct"] + context["right_pct"] + context["gap_pct"]
                    self.assertAlmostEqual(total, 100, places=1)

    def test_a_wider_split_really_is_wider(self):
        block = TwoImageBlock()
        context = block.get_context(block.to_python(self.stored(split="67-33")))
        self.assertGreater(context["left_pct"], context["right_pct"])
