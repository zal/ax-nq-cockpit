# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""EDC Management Cockpit routes.
"""
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, render_template, request

from db import db
from routes.auth import login_required
from utils.edc_utils import fetch_own_catalog, list_assets

edc_bp = Blueprint("edc", __name__, url_prefix="/edc")


def _get_settings():
    s = db.get_connector_settings()
    s["connector_management_url"] = (
        f"{s['connector_hostname']}/management" if s["connector_hostname"] else ""
    )
    return s


# ---- Routes -----------------------------------------------------------------


@edc_bp.route("/cockpit")
@login_required
def edc_cockpit():
    return render_template("edc_cockpit.html", connector=_get_settings())


@edc_bp.route("/api/partners", methods=["GET", "POST"])
@login_required
def list_partners():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        edc_connector_did = (data.get("edc_connector_did") or "").strip()
        if not edc_connector_did:
            return jsonify({"error": "edc_connector_did is required"}), 400
        db.upsert_trusted_partner(
            edc_connector_did=edc_connector_did,
            edc_hostname=(data.get("edc_hostname") or "").strip() or None,
            keycloak_url=data.get("keycloak_url"),
            label=data.get("label"),
        )
        return jsonify({"created": edc_connector_did}), 201
    return jsonify({"partners": db.get_trusted_partners()})


@edc_bp.route("/api/partners/<path:edc_connector_did>", methods=["DELETE"])
@login_required
def delete_partner(edc_connector_did):
    db.remove_trusted_partner(edc_connector_did)
    return jsonify({"removed": edc_connector_did})


@edc_bp.route("/api/connector-status")
@login_required
def connector_status():
    s = _get_settings()
    online = False
    if s["connector_hostname"]:
        headers = {"Content-Type": "application/json"}
        if s["x_api_key"]:
            headers["X-Api-Key"] = s["x_api_key"]
        try:
            _, status_code = list_assets(s["connector_hostname"], headers)
            online = status_code < 400
        except Exception:
            online = False
    return jsonify(
        {
            "online": online,
            "url": s["connector_management_url"],
            "legal_entity_id": s["legal_entity_id"],
        }
    )


@edc_bp.route("/api/connector-settings", methods=["POST"])
@login_required
def update_connector_settings():
    data = request.get_json() or {}
    current = db.get_connector_settings()
    db.save_connector_settings(
        connector_hostname=data.get("url", current["connector_hostname"]),
        identity_hostname=data.get("identity_hostname", current["identity_hostname"]),
        x_api_key=data.get("api_key", current["x_api_key"]),
        legal_entity_id=data.get("legal_entity_id", current["legal_entity_id"]),
    )
    return jsonify({"success": True, "connector": _get_settings()})


@edc_bp.route("/api/transport-mode", methods=["GET", "POST"])
@login_required
def transport_mode():
    if request.method == "GET":
        return jsonify({"mode": db.get_transport_mode()})

    data = request.get_json() or {}
    mode = (data.get("mode") or "mock").strip().lower()
    if mode not in ("mock", "edc"):
        return jsonify({"error": "mode must be 'mock' or 'edc'"}), 400

    if mode == "edc":
        s = _get_settings()
        missing = []
        if not s.get("connector_hostname"):
            missing.append("Connector Base URL")
        if not s.get("identity_hostname"):
            missing.append("Identity Hub Base URL")
        if not s.get("x_api_key"):
            missing.append("API Key")
        if not s.get("legal_entity_id"):
            missing.append("Legal Entity ID")
        if not db.get_trusted_partners():
            missing.append("at least one trusted partner")
        if missing:
            return jsonify({"error": "Prerequisites not met", "missing": missing}), 400

    db.save_transport_mode(mode)
    from transport.base import reset_transport

    reset_transport()
    return jsonify({"success": True, "mode": mode})


@edc_bp.route("/api/query-catalog", methods=["POST"])
@login_required
def query_catalog():
    s = _get_settings()
    if not s["connector_hostname"]:
        return jsonify({"error": "Connector URL not configured"}), 400
    identity_netloc = urlparse(s["identity_hostname"]).netloc or s["identity_hostname"]
    if not identity_netloc:
        return jsonify({"error": "Identity Hub URL not configured"}), 400
    headers = {"Content-Type": "application/json"}
    if s["x_api_key"]:
        headers["X-Api-Key"] = s["x_api_key"]
    try:
        result = fetch_own_catalog(s["connector_hostname"], identity_netloc, headers)
        if isinstance(result, requests.Response):
            return (
                jsonify({"error": f"HTTP {result.status_code}", "detail": result.text}),
                result.status_code,
            )
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
