# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Authentication + shared landing routes (the `nq` blueprint).
Login goes through Keycloak via a plain OpenID Connect authorization-code flow.
"""
import secrets
from functools import wraps
from urllib.parse import urlencode, urljoin, urlparse

import requests
from flask import Blueprint, abort, redirect, render_template, request, session, url_for

import config
from db import db

nq_bp = Blueprint("nq", __name__)

_REDIRECT_PATH = "/auth/callback"


def is_safe_url(target):
    """Ensures the target URL is relative and on the same host."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


class _User:
    def __init__(self, username):
        self.username = username

    @property
    def is_authenticated(self):
        return bool(self.username)


def current_user():
    return _User(session.get("username"))


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user().is_authenticated:
            return redirect(url_for("nq.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def role_home_url():
    """Send the user to the top-level portal after login."""
    return url_for("nq.portal")


def init_auth(app):
    @app.context_processor
    def _inject_user():
        return {"current_user": current_user(), "role": config.ROLE}


# --- routes ----------------------------------------------------------------
@nq_bp.route("/")
def company_info():
    if current_user().is_authenticated:
        return redirect(role_home_url())
    return redirect(url_for("nq.login"))


@nq_bp.route("/login")
def login():
    if not config.AUTH_ENABLED:
        session["username"] = f"{config.ROLE}@example.com"
        return redirect(role_home_url())

    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    next_url = request.args.get("next")
    if next_url and is_safe_url(next_url):
        session["oauth_next"] = next_url
    else:
        session["oauth_next"] = role_home_url()
    next_url = (
        request.args.get("next")
        if request.args.get("next") and is_safe_url(request.args.get("next"))
        else role_home_url()
    )
    params = {
        "client_id": config.OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": config.PUBLIC_URL + _REDIRECT_PATH,
        "state": state,
    }
    return redirect(
        f"{config.OIDC_ISSUER}/protocol/openid-connect/auth?{urlencode(params)}"
    )


@nq_bp.route(_REDIRECT_PATH)
def callback():
    if request.args.get("state") != session.pop("oauth_state", None):
        abort(400, "OAuth state mismatch")
    code = request.args.get("code")
    if not code:
        abort(400, "Missing authorization code")

    token = requests.post(
        f"{config.OIDC_INTERNAL_ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.PUBLIC_URL + _REDIRECT_PATH,
            "client_id": config.OIDC_CLIENT_ID,
            "client_secret": config.OIDC_CLIENT_SECRET,
        },
        timeout=10,
    ).json()
    access_token = token.get("access_token")
    if not access_token:
        abort(401, "Token exchange failed")

    userinfo = requests.get(
        f"{config.OIDC_INTERNAL_ISSUER}/protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    ).json()
    session["username"] = (
        userinfo.get("preferred_username") or userinfo.get("email") or "user"
    )
    session["id_token"] = token.get("id_token", "")
    return redirect(session.pop("oauth_next", None) or role_home_url())


@nq_bp.route("/logout")
def logout():
    id_token = session.get("id_token", "")
    session.clear()
    if config.AUTH_ENABLED:
        params = {
            "post_logout_redirect_uri": config.PUBLIC_URL + "/",
            "id_token_hint": id_token,
        }
        return redirect(
            f"{config.OIDC_ISSUER}/protocol/openid-connect/logout?{urlencode(params)}"
        )
    return redirect(url_for("nq.login"))


@nq_bp.route("/portal")
@login_required
def portal():
    return render_template("portal.html")


@nq_bp.route("/home")
@login_required
def choose_role():
    return redirect(url_for("nq.portal"))


@nq_bp.route("/nq-cockpit")
@login_required
def nq_cockpit():
    grouped = {"notifications_customer": {}, "notifications_supplier": {}}
    grouped[f"notifications_{config.ROLE}"] = db.notifications_dict()
    return render_template("nq_cockpit.html", notifications=grouped)
