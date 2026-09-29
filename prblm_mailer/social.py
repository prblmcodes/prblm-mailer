"""The platforms the Social links block offers, and their brand colours.

Data only, and deliberately free of Django imports, so `scripts/build_icons.py` can
read the same list when it rasterises the PNGs — the slugs here and the filenames in
`static/prblm_mailer/icons/` must never drift apart.

Ordered by how often a newsletter actually links to them, because that order is what
the editor's dropdown shows.
"""

# slug: (label, default chip colour — the platform's own brand colour, used when
# the editor picks no icon colour of their own)
PLATFORMS = {
    "facebook": ("Facebook", "#1877F2"),
    "instagram": ("Instagram", "#E4405F"),
    "x": ("X (Twitter)", "#000000"),
    "linkedin": ("LinkedIn", "#0A66C2"),
    "youtube": ("YouTube", "#FF0000"),
    "tiktok": ("TikTok", "#000000"),
    "threads": ("Threads", "#000000"),
    "whatsapp": ("WhatsApp", "#25D366"),
    "pinterest": ("Pinterest", "#BD081C"),
    "spotify": ("Spotify", "#1DB954"),
    "bluesky": ("Bluesky", "#0285FF"),
    "github": ("GitHub", "#181717"),
    "medium": ("Medium", "#000000"),
    "email": ("Email", "#5b6472"),
    "website": ("Website", "#5b6472"),
}


def platform_choices():
    """`[(slug, label), …]` for a ChoiceBlock."""
    return [(slug, label) for slug, (label, _colour) in PLATFORMS.items()]


def brand_color(slug):
    """The platform's own colour, or an empty string for an unknown slug."""
    return PLATFORMS.get(slug, ("", ""))[1]
