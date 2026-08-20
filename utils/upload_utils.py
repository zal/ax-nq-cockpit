# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

import os
import uuid

from flask import send_file, url_for

import config


# --- file upload/serve helpers, shared by both roles' routes ---------------
def save_upload(base_dir, nq_id, file_obj, default_ext, endpoint):
    os.makedirs(os.path.join(base_dir, nq_id), exist_ok=True)
    original = file_obj.filename
    ext = original.rsplit(".", 1)[1].lower() if "." in original else default_ext
    unique = f"{uuid.uuid4().hex}.{ext}"
    file_obj.save(os.path.join(base_dir, nq_id, unique))
    rel = url_for(endpoint, nq_id=nq_id, filename=unique)
    return {
        "url": rel,
        "url_aas": config.OWN_URL + rel,
        "filename": original,
        "content_type": file_obj.content_type,
    }


def upload_many(base_dir, nq_id, files, default_ext, endpoint):
    return [
        save_upload(base_dir, nq_id, f, default_ext, endpoint)
        for f in files
        if f and f.filename
    ]


def delete_upload(base_dir, nq_id, url):
    filename = url.rsplit("/", 1)[-1]
    path = os.path.join(base_dir, nq_id, filename)
    if os.path.exists(path):
        os.remove(path)


def serve_upload(nq_id, filename, fs_dir, fallback_mime):
    path = os.path.join(fs_dir, nq_id, filename)
    return (
        send_file(path, mimetype=fallback_mime)
        if os.path.exists(path)
        else ("Not found", 404)
    )
