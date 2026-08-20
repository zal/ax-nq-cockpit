# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Deciding which URL a browser should use for an attachment.

Uploaded files carry two URLs (`utils.upload_utils.save_upload`): `url` is the
path this app serves them under, `url_aas` the absolute one that travels in the
AAS submodel. A pulled partner attachment therefore arrives with both set to
the partner's absolute URL, which is reachable server-to-server but not from
the browser (under Docker it is a container hostname). Those — and only those —
are routed through this side's proxy (`routes/files.py`), which fetches the
stored `url_aas`.
"""

import hashlib
from urllib.parse import urlsplit

from flask import url_for

import config


def _origin(url):
    parts = urlsplit(url or "")
    return (parts.scheme, parts.netloc) if parts.scheme and parts.netloc else None


_PARTNER_ORIGIN = _origin(config.PARTNER_URL)


def aas_url(attachment):
    """The absolute URL an attachment travels under, if it has one."""
    if not isinstance(attachment, dict):
        return ""
    return attachment.get("url_aas") or attachment.get("url") or ""


def is_partner_hosted(attachment):
    """True for a file served by the partner app. Local attachments (relative
    `url`) and ones pointing somewhere else entirely are left alone."""
    return _PARTNER_ORIGIN is not None and _origin(aas_url(attachment)) == (
        _PARTNER_ORIGIN
    )


def key_for(attachment):
    """Opaque, stable handle for an attachment, derived from its URL."""
    return hashlib.sha256(aas_url(attachment).encode()).hexdigest()[:16]


def browser_url(attachment):
    """The URL to put in an <img>/<a>. Registered as the `attachment_url`
    template global in app.py."""
    if is_partner_hosted(attachment):
        return url_for("files.partner_file", key=key_for(attachment))
    return (attachment or {}).get("url") or ""


def iter_attachments(nq):
    """Every attachment dict reachable from an nq record."""
    desc = nq.get("NonQualityDescription") or {}
    for field in ("defectImage", "defectDocument"):
        yield from (a for a in (desc.get(field) or []) if isinstance(a, dict))
    for action in nq.get("ContainmentActions") or []:
        for reference in action.get("ActionReference") or []:
            reference_file = (reference or {}).get("referenceFile")
            if isinstance(reference_file, dict):
                yield reference_file
    for disposition in nq.get("Disposition") or []:
        for info in disposition.get("AdditionalInformation") or []:
            yield from (
                a
                for a in ((info or {}).get("additionalDocument") or [])
                if isinstance(a, dict)
            )


def find_by_key(nqs, key):
    """The partner-hosted attachment behind `key`, or None. Only attachments
    actually referenced by one of `nqs` resolve, so the proxy cannot be pointed
    at arbitrary partner paths."""
    for nq in nqs:
        for attachment in iter_attachments(nq):
            if is_partner_hosted(attachment) and key_for(attachment) == key:
                return attachment
    return None
