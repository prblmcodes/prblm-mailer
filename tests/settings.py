"""Minimal Django/Wagtail settings to load and test prblm_mailer standalone.

Not a real project — just enough for the app to import, migrate, and run tests
against, with no reference to beMore.
"""

SECRET_KEY = "test-only-not-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]
USE_TZ = True

INSTALLED_APPS = [
    # our package
    "prblm_mailer",
    # concrete form page exercising the abstract form bases (tests only)
    "tests.testapp",
    # its runtime dependencies
    "newsletter",
    "anymail",
    "sorl.thumbnail",
    # wagtail stack (trimmed to what the package needs)
    "wagtail.contrib.forms",
    "wagtail.contrib.settings",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
    # django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.urls"
SITE_ID = 1

DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": [],
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.request",
            ]
        },
    }
]

STATIC_URL = "/static/"
WAGTAIL_SITE_NAME = "Test"
WAGTAILADMIN_BASE_URL = "http://localhost:8000"

# The package reads only this. Left near-empty so defaults (conf.py) are exercised.
PRBLM_MAILER = {
    "FROM_EMAIL": "test@example.com",
    "FROM_NAME": "Test Sender",
}

# Send to console in tests; nothing leaves.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
