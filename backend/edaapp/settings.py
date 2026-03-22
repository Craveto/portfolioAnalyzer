from __future__ import annotations

import os
from pathlib import Path
from typing import Final

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent.parent
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-unsafe-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]


def _module_available(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


WHITENOISE_AVAILABLE: Final[bool] = _module_available("whitenoise")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "portfolio",
    "api",
    "analysis",
    "accounts",
    "watchlist",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise is recommended for production static files; keep optional for dev.
    *(
        ["whitenoise.middleware.WhiteNoiseMiddleware"]
        if WHITENOISE_AVAILABLE
        else []
    ),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "edaapp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "edaapp.wsgi.application"


DATABASE_URL = (os.getenv("DATABASE_POOL_URL") or os.getenv("DATABASE_URL") or "").strip()
DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").lower()
DB_CONN_MAX_AGE_RAW = (os.getenv("DB_CONN_MAX_AGE") or "0").strip()
try:
    DB_CONN_MAX_AGE = max(0, int(DB_CONN_MAX_AGE_RAW))
except ValueError:
    DB_CONN_MAX_AGE = 0

if DATABASE_URL:
    try:
        import dj_database_url  # type: ignore

        DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=DB_CONN_MAX_AGE, ssl_require=True)}
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    except Exception as e:
        raise RuntimeError("DATABASE_URL is set but 'dj-database-url' is not installed.") from e
elif DB_ENGINE == "mssql":
    DATABASES = {
        "default": {
            "ENGINE": "mssql",
            "NAME": os.getenv("MSSQL_NAME", "EDAAPP"),
            "USER": os.getenv("MSSQL_USER", "sa"),
            "PASSWORD": os.getenv("MSSQL_PASSWORD", ""),
            "HOST": os.getenv("MSSQL_HOST", "localhost"),
            "PORT": os.getenv("MSSQL_PORT", "1433"),
            "OPTIONS": {
                "driver": os.getenv("MSSQL_OPTIONS_DRIVER", "ODBC Driver 18 for SQL Server"),
                "extra_params": "TrustServerCertificate=yes",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
# Render/collectstatic expects a filesystem path (string is safest across envs).
STATIC_ROOT = os.getenv("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles"))
if WHITENOISE_AVAILABLE:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174",
    ).split(",")
    if o.strip()
]

# Local dev convenience: if DEBUG is on, allow all origins so the UI never
# gets blocked by stale env/processes or origin mismatches during demos.
# (Token auth uses headers, not cookies, so this is safe for local dev.)
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174",
    ).split(",")
    if o.strip()
]


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ),
}
