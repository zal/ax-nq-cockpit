# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Supplier portal (`/supplier`). Thin controllers over workflow.py + db.py.
"""

import json
import os
import time
from queue import Empty, Queue

from flask import Blueprint, Response, redirect, render_template, request, url_for

import config
import workflow
from db import db
from routes.auth import login_required
from utils.form_utils import build_containment_dict, build_disposition_dict
from utils.upload_utils import serve_upload, upload_many

supplier_bp = Blueprint("supplier", __name__, url_prefix="/supplier")

_pull_progress: Queue = Queue(maxsize=20)
_disposition_progress: Queue = Queue(maxsize=20)


def _send_pull_progress(step: int, message: str, total: int = 4) -> None:
    try:
        _pull_progress.put_nowait(
            {"step": step, "message": message, "total": total, "nq_id": ""}
        )
    except Exception:
        pass
    time.sleep(1)


def _send_progress_disposition(step: int, message: str, total: int = 5) -> None:
    try:
        _disposition_progress.put_nowait(
            {"step": step, "message": message, "total": total}
        )
    except Exception:
        pass
    time.sleep(1)


CONTAINMENT_FILES_DIR = os.path.join(config.DATA_DIR, "containment_files")


@supplier_bp.route("/")
@login_required
def supplier_inbox():
    existing = set(db.all_nqs_dict().keys())
    notifications = {
        nid: n for nid, n in db.notifications_dict().items() if nid not in existing
    }
    return render_template(
        "supplier.html", nq=db.received_nqs_dict(), notifications=notifications
    )


@supplier_bp.route("/nq/<string:nq_id>")
@login_required
def view_nq(nq_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    pending_notification = (
        db.get_notification(nq_id) if nq.get("PartnerUpdatePending") else None
    )
    return render_template(
        "nq_detail.html", nq=nq, pending_notification=pending_notification
    )


@supplier_bp.route("/fetch_nq/<string:nq_id>", methods=["POST"])
@login_required
def fetch_nq_data(nq_id):
    """Pull the offered NQ asset from the customer and store it locally. Used
    both for the initial inbox fetch and for pulling a partner update from
    within view_nq; either way we land on the NQ's detail page afterwards."""

    while not _pull_progress.empty():
        try:
            _pull_progress.get_nowait()
        except Empty:
            break
    try:
        workflow.pull_from_partner(nq_id, on_progress=_send_pull_progress)
        db.delete_notifications_for(nq_id)
    except Exception as exc:
        print(f"[supplier] fetch {nq_id} failed: {exc}")
    return redirect(url_for("supplier.view_nq", nq_id=nq_id))


@supplier_bp.route("/dismiss_notification/<string:nq_id>", methods=["POST"])
@login_required
def dismiss_notification(nq_id):
    db.delete_notifications_for(nq_id)
    return redirect(url_for("supplier.supplier_inbox"))


@supplier_bp.route("/nq/<string:nq_id>/submit_disposition", methods=["POST"])
@login_required
def supplier_submit_disposition(nq_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    nq.setdefault("Disposition", []).append(
        build_disposition_dict(nq_id, creator="Supplier")
    )
    workflow.save_and_publish(
        nq_id,
        nq,
        kind="DISPOSITION_ADDED",
        message="Supplier submitted a new disposition.",
        on_progress=_send_progress_disposition,
    )
    return redirect(url_for("supplier.view_nq", nq_id=nq_id))


@supplier_bp.route(
    "/nq/<string:nq_id>/disposition/<int:index>/respond", methods=["POST"]
)
@login_required
def supplier_respond_disposition(nq_id, index):
    """Accept/reject the customer's disposition proposal at `index` and notify
    them so their copy converges to the same decision."""

    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    dispositions = nq.get("Disposition", [])
    if not (0 <= index < len(dispositions)):
        return "Invalid disposition index", 404
    disposition = dispositions[index]
    if disposition.get("dispositionCreator") == "Supplier":
        return "Cannot respond to your own disposition", 400
    if (disposition.get("acceptanceStatus") or "pending") != "pending":
        return redirect(url_for("supplier.view_nq", nq_id=nq_id))
    decision = request.form.get("decision")
    if decision not in ("accepted", "rejected"):
        return "Invalid decision", 400
    disposition["acceptanceStatus"] = decision
    disposition["_statusUpdatedBy"] = "Supplier"
    workflow.save_and_publish(
        nq_id,
        nq,
        kind="DISPOSITION_STATUS_UPDATED",
        message=f"Supplier {decision} a disposition.",
        on_progress=_send_progress_disposition,
    )
    return redirect(url_for("supplier.view_nq", nq_id=nq_id))


@supplier_bp.route("/nq/<string:nq_id>/create_containment", methods=["POST"])
@login_required
def supplier_create_containment(nq_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    reference_files = upload_many(
        CONTAINMENT_FILES_DIR,
        nq_id,
        request.files.getlist("referenceFile"),
        "pdf",
        "supplier.serve_containment_file",
    )
    reference_file = reference_files[0] if reference_files else None
    nq.setdefault("ContainmentActions", []).append(
        build_containment_dict(
            nq_id, default_action_party="Supplier", reference_file=reference_file
        )
    )
    workflow.save_and_publish(
        nq_id,
        nq,
        kind="CONTAINMENT_ADDED",
        message="Supplier created a new containment action.",
        on_progress=_send_progress_disposition,
    )
    return redirect(url_for("supplier.view_nq", nq_id=nq_id))


@supplier_bp.route("/containment_files/<string:nq_id>/<string:filename>")
def serve_containment_file(nq_id, filename):
    return serve_upload(nq_id, filename, CONTAINMENT_FILES_DIR, "application/*")


@supplier_bp.route("/nq/<string:nq_id>/containment/<string:action_id>")
@login_required
def view_containment_action(nq_id, action_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    action = next(
        (a for a in nq.get("ContainmentActions", []) if a.get("actionId") == action_id),
        None,
    )
    if not action:
        return "Invalid Containment Action ID", 404
    return render_template(
        "view_containment_action.html",
        nq=nq,
        action=action,
        nq_id=nq_id,
        back_url=url_for("supplier.view_nq", nq_id=nq_id),
    )


# --- real-time progress stream (queue-driven, works for both mock and EDC) --
@supplier_bp.route("/progress_nq")
@login_required
def progress_stream_nq():
    def gen():
        try:
            while True:
                try:
                    data = _pull_progress.get(timeout=30)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("step") == data.get("total", 4):
                        break
                except Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass

    return Response(gen(), mimetype="text/event-stream")


@supplier_bp.route("/progress_disposition")
@login_required
def progress_stream_disposition():
    def gen():
        try:
            while True:
                try:
                    data = _disposition_progress.get(timeout=30)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("step") == data.get("total", 5):
                        break
                except Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass

    return Response(gen(), mimetype="text/event-stream")
