# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Role-agnostic serving of partner-hosted attachments.
"""

import requests
from flask import Blueprint, Response

import config
from db import db
from routes.auth import login_required
from utils import attachments

files_bp = Blueprint("files", __name__, url_prefix="/files")


@files_bp.route("/partner/<string:key>")
@login_required
def partner_file(key):
    """Stream a file hosted by the partner app. Its URL is only reachable
    server-to-server (a container hostname under Docker), so the browser asks
    us for it and we fetch it on the browser's behalf.

    `key` identifies an attachment inside the NQs we hold; we then fetch the
    URL stored on that attachment verbatim, so nothing here needs to know how
    the partner lays out its routes."""
    attachment = attachments.find_by_key((nq for _, nq in db.all_nqs()), key)
    if attachment is None:
        return "Not found", 404
    url = attachments.aas_url(attachment)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"[{config.ROLE}] proxying partner file {url} failed: {exc}")
        return "Failed to fetch file from partner", 502
    fallback = attachment.get("content_type") or "application/octet-stream"
    return Response(
        resp.content,
        content_type=resp.headers.get("Content-Type") or fallback,
    )
