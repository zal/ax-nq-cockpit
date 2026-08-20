# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Single, env-driven configuration. One container == one role.

Everything is read from environment variables so the same image can run as the
customer or the supplier (see docker-compose.yml).
"""

import os


def _bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- role / identity -------------------------------------------------------
ROLE = os.environ.get("ROLE", "customer").strip().lower()
if ROLE not in ("customer", "supplier"):
    raise ValueError(f"ROLE must be 'customer' or 'supplier', got {ROLE!r}")
PARTNER_ROLE = "supplier" if ROLE == "customer" else "customer"

# --- web -------------------------------------------------------------------
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
DEBUG = _bool(os.environ.get("DEBUG"), True)
_default_partner = (
    "http://localhost:5002" if ROLE == "customer" else "http://localhost:5001"
)
PARTNER_URL = os.environ.get("PARTNER_URL", _default_partner).rstrip("/")
PARTNER_PUBLIC_URL = os.environ.get("PARTNER_PUBLIC_URL", PARTNER_URL).rstrip("/")
OWN_URL = os.environ.get("OWN_URL", f"http://localhost:{PORT}").rstrip("/")
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")
DATASPACE_SECRET = os.environ.get("DATASPACE_SECRET", "")

# --- Basyx ---------------------------------------------------------------
BASYX_ENV_URL = os.environ.get("BASYX_ENV_URL", "").rstrip("/")
BASYX_ENABLED = bool(BASYX_ENV_URL)

# --- Keycloak OIDC (app login) ---------------------------------------------
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "").rstrip("/")
OIDC_INTERNAL_ISSUER = os.environ.get("OIDC_INTERNAL_ISSUER", OIDC_ISSUER).rstrip("/")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "nq-cockpit")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
AUTH_ENABLED = bool(OIDC_ISSUER)

# --- storage ---------------------------------------------------------------
DATA_DIR = os.environ.get(
    "DATA_DIR", os.path.join(os.path.dirname(__file__), "instance")
)
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, f"nq_{ROLE}.db"))
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(DATA_DIR, "defect_images"))
