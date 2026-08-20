# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Customer portal (`/customer`). Thin controllers over workflow.py + db.py. Handles requests.
"""
import json
import os
import time
from datetime import datetime
from queue import Empty, Queue

from flask import (
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

import config
import workflow
from db import db
from routes.auth import login_required
from utils.form_utils import (
    build_containment_dict,
    build_disposition_dict,
    generate_random_id,
)
from utils.upload_utils import delete_upload, serve_upload, upload_many

customer_bp = Blueprint("customer", __name__, url_prefix="/customer")

_nq_progress: Queue = Queue(maxsize=20)
_disposition_progress: Queue = Queue(maxsize=20)
_pull_progress: Queue = Queue(maxsize=20)


def _send_progress_nq(step: int, message: str, total: int = 5) -> None:
    try:
        _nq_progress.put_nowait({"step": step, "message": message, "total": total})
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


def _send_progress_pull(step: int, message: str, total: int = 4) -> None:
    try:
        _pull_progress.put_nowait({"step": step, "message": message, "total": total})
    except Exception:
        pass
    time.sleep(1)


DEFECT_IMAGES_DIR = os.path.join(config.DATA_DIR, "defect_images")
DEFECT_DOCUMENTS_DIR = os.path.join(config.DATA_DIR, "defect_documents")
CONTAINMENT_FILES_DIR = os.path.join(config.DATA_DIR, "containment_files")

_available_parts = {}

_SHARE_NQ_REQUIRED_FIELDS = (
    "nonQualityTitle",
    "DigitalNameplate",
    "NonQualityQuantity",
    "problemShortDescription",
    "problemLongDescription",
    "issueGroup",
    "issueCode",
    "stepOfProduction",
    "detectedHow",
    "detectedWhen",
    "detectedWhere",
    "detectedByWhom",
    "affectedPurchaseOrderNumber",
    "purchaseOrderPositionNumber",
    "customerACAGECode",
    "customerGroupName",
    "customerOrganizationName",
    "customerPlantCode",
    "customerPlantName",
    "supplierACAGECode",
)


# --- defect / containment file upload + serving ----------------------------
@customer_bp.route("/defect_images/<string:nq_id>/<string:filename>")
def serve_defect_image(nq_id, filename):
    return serve_upload(nq_id, filename, DEFECT_IMAGES_DIR, "image/*")


@customer_bp.route("/defect_documents/<string:nq_id>/<string:filename>")
def serve_defect_document(nq_id, filename):
    return serve_upload(nq_id, filename, DEFECT_DOCUMENTS_DIR, "application/*")


@customer_bp.route("/containment_files/<string:nq_id>/<string:filename>")
def serve_containment_file(nq_id, filename):
    return serve_upload(nq_id, filename, CONTAINMENT_FILES_DIR, "application/*")


@customer_bp.route("/api/upload_defect_images/<string:nq_id>", methods=["POST"])
@login_required
def api_upload_defect_images(nq_id):
    if db.get_nq(nq_id) is None:
        return jsonify({"error": "Invalid NQ ID"}), 404
    images = upload_many(
        DEFECT_IMAGES_DIR,
        nq_id,
        request.files.getlist("defectImage"),
        "jpg",
        "customer.serve_defect_image",
    )
    return jsonify({"success": True, "images": images})


# --- parts master autofill -------------------------------------------------
@customer_bp.route("/api/get_available_parts")
@login_required
def get_available_parts():
    parts = []
    part_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "part")
    if os.path.isdir(part_dir):
        for filename in sorted(os.listdir(part_dir)):
            if not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(part_dir, filename)) as f:
                    data = json.load(f)
            except Exception:
                continue
            number = data.get("PartIdentification", {}).get("customerPartNumber", "")
            if number:
                parts.append({"value": str(number), "data": data})
    parts.sort(key=lambda p: p["value"])
    _available_parts.clear()
    _available_parts.update({p["value"]: p["data"] for p in parts})
    return jsonify(parts)


@customer_bp.route("/api/get_part_info")
@login_required
def get_part_info():
    data = _available_parts.get(request.args.get("customerPartNumber"))
    if not data:
        return jsonify({})
    part = data.get("PartIdentification", {})
    disc = data.get("NonQualityDiscovery", {})
    po = data.get("ImpactedPurchaseOrder", {})
    collab = data.get("PartnerCollaboration", {})
    scope = data.get("ProductScope", {})
    return jsonify(
        {
            "customerPartName": part.get("customerPartName", ""),
            "partClass": part.get("partClass", ""),
            "DigitalNameplate": part.get("DigitalNameplate", ""),
            "traceabilityType": part.get("traceabilityType", ""),
            "traceabilityNumber": part.get("traceabilityNumber", ""),
            "stepOfProduction": disc.get("stepOfProduction", ""),
            "msn": disc.get("msn", ""),
            "versionOfAircraft": disc.get("versionOfAircraft", ""),
            "ataSection": disc.get("ataSection", ""),
            "affectedPurchaseOrderNumber": po.get("affectedPurchaseOrderNumber", ""),
            "purchaseOrderPositionNumber": po.get("purchaseOrderPositionNumber", ""),
            "customerACAGECode": collab.get("customerACAGECode", ""),
            "customerGroupName": collab.get("customerGroupName", ""),
            "customerOrganizationName": collab.get("customerOrganizationName", ""),
            "customerPlantCode": collab.get("customerPlantCode", ""),
            "customerPlantName": collab.get("customerPlantName", ""),
            "supplierACAGECode": collab.get("supplierACAGECode", ""),
            "airlineCustomer": scope.get("airlineCustomer", ""),
            "finalCustomer": scope.get("finalCustomer", ""),
            "commodity": scope.get("commodity", ""),
            "subCommodity": scope.get("subCommodity", ""),
            "program": scope.get("program", ""),
        }
    )


# --- NQ lifecycle ----------------------------------------------------------
@customer_bp.route("/customer_home", methods=["GET", "POST"])
@login_required
def customer_home():
    return render_template("customer_home.html", nqs=db.local_nqs_dict())


@customer_bp.route("/customer_form", methods=["GET", "POST"])
@login_required
def customer_form():
    if request.method == "GET":
        return render_template(
            "customer.html",
            transport_mode=db.get_transport_mode(),
            partner_url=config.PARTNER_PUBLIC_URL,
        )

    missing = [
        f for f in _SHARE_NQ_REQUIRED_FIELDS if not (request.form.get(f) or "").strip()
    ]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    nq_id = generate_random_id(length=8)
    images = upload_many(
        DEFECT_IMAGES_DIR,
        nq_id,
        request.files.getlist("defectImage"),
        "jpg",
        "customer.serve_defect_image",
    )
    documents = upload_many(
        DEFECT_DOCUMENTS_DIR,
        nq_id,
        request.files.getlist("defectDocument"),
        "pdf",
        "customer.serve_defect_document",
    )
    uuids = request.form.getlist("uuid[]")
    names = request.form.getlist("featureName[]")

    nq = {
        "NonQualityHeader": {
            "nonQualityId": nq_id,
            "nonQualityTitle": request.form.get("nonQualityTitle"),
            "nonQualityStatus": "OPEN",
            "nonQualityCreationDate": datetime.now().astimezone().isoformat(),
            "nonQualityLastUpdateDate": datetime.now().astimezone().isoformat(),
            "customerComment": request.form.get("customerComment"),
        },
        "NonQualityDescription": {
            "problemShortDescription": request.form.get("problemShortDescription"),
            "problemLongDescription": request.form.get("problemLongDescription"),
            "issueGroup": request.form.get("issueGroup"),
            "issueCode": request.form.get("issueCode"),
            "defectImage": images,
            "defectDocument": documents,
            "safetyRelated": request.form.get("safetyRelated") == "on",
            "subPartAffectedComponent": [f"{u}:{n}" for u, n in zip(uuids, names)],
        },
        "NonQualityDiscovery": {
            "stepOfProduction": request.form.get("stepOfProduction"),
            "msn": request.form.get("msn"),
            "versionOfAircraft": request.form.get("versionOfAircraft"),
            "ataSection": request.form.get("ataSection"),
            "detectedHow": request.form.get("detectedHow"),
            "detectedWhen": request.form.get("detectedWhen"),
            "detectedWhere": request.form.get("detectedWhere"),
            "detectedByWhom": request.form.get("detectedByWhom"),
        },
        "ProductScope": {
            "airlineCustomer": request.form.get("airlineCustomer"),
            "finalCustomer": request.form.get("finalCustomer"),
            "commodity": request.form.get("commodity"),
            "subCommodity": request.form.get("subCommodity"),
            "program": request.form.get("program"),
        },
        # Multi-part in the model; the form authors a single part.
        "PartIdentification": [
            {
                "partDigitalNameplate": request.form.get("DigitalNameplate") or "",
                "affectedQuantity": request.form.get("NonQualityQuantity"),
                "traceabilityType": request.form.get("traceabilityType"),
                "traceabilityNumber": request.form.get("traceabilityNumber"),
                "partClass": request.form.get("partClass"),
                "customerPartNumber": request.form.get("customerPartNumber"),
                "customerPartName": request.form.get("customerPartName"),
            }
        ],
        "ImpactedPurchaseOrder": {
            "affectedPurchaseOrderNumber": request.form.get(
                "affectedPurchaseOrderNumber"
            ),
            "purchaseOrderPositionNumber": request.form.get(
                "purchaseOrderPositionNumber"
            ),
        },
        "CollaborationPartners": {
            "CustomerSite": {
                "customerACAGECode": request.form.get("customerACAGECode"),
                "customerGroupName": request.form.get("customerGroupName"),
                "customerOrganizationName": request.form.get(
                    "customerOrganizationName"
                ),
                "customerPlantCode": request.form.get("customerPlantCode"),
                "customerPlantName": request.form.get("customerPlantName"),
            },
            "SupplierSite": {
                "supplierACAGECode": request.form.get("supplierACAGECode")
            },
        },
    }

    workflow.save_and_publish(
        nq_id,
        nq,
        kind="NEW_NQ_CREATED",
        message="A new Non-Quality has been created and is available to fetch.",
        on_progress=_send_progress_nq,
    )
    return render_template("customer_home.html", nqs=db.local_nqs_dict())


@customer_bp.route("/nq/<string:nq_id>")
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


@customer_bp.route("/nq/<string:nq_id>/fetch_update", methods=["POST"])
@login_required
def fetch_update(nq_id):
    """Pull the supplier's pending update (disposition/containment) via EDC."""
    try:
        workflow.pull_from_partner(nq_id, on_progress=_send_progress_pull)
        db.delete_notifications_for(nq_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[customer] fetch_update for {nq_id} failed: {exc}")
    return redirect(url_for("customer.view_nq", nq_id=nq_id))


@customer_bp.route("/nq/close/<string:nq_id>", methods=["GET", "POST"])
@login_required
def close_nq(nq_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    nq["NonQualityHeader"]["nonQualityStatus"] = "CLOSED"
    workflow.save_and_publish(
        nq_id,
        nq,
        kind="NQ_CLOSED",
        message="This Non-Quality has been closed by the Customer.",
    )
    return render_template("customer_home.html", nqs=db.local_nqs_dict())


@customer_bp.route("/nq/<string:nq_id>/submit_disposition", methods=["POST"])
@login_required
def submit_disposition(nq_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    nq.setdefault("Disposition", []).append(
        build_disposition_dict(nq_id, creator="Customer")
    )
    nq["NonQualityHeader"]["nonQualityLastUpdateDate"] = datetime.now().isoformat()
    workflow.save_and_publish(
        nq_id,
        nq,
        kind="DISPOSITION_ADDED",
        message="Customer submitted a new disposition.",
        on_progress=_send_progress_disposition,
    )
    return redirect(url_for("customer.view_nq", nq_id=nq_id))


@customer_bp.route(
    "/nq/<string:nq_id>/disposition/<int:index>/respond", methods=["POST"]
)
@login_required
def respond_disposition(nq_id, index):
    """Accept/reject the supplier's disposition proposal at `index` and notify
    them so their copy converges to the same decision."""

    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    dispositions = nq.get("Disposition", [])
    if not (0 <= index < len(dispositions)):
        return "Invalid disposition index", 404
    disposition = dispositions[index]
    if disposition.get("dispositionCreator") == "Customer":
        return "Cannot respond to your own disposition", 400
    if (disposition.get("acceptanceStatus") or "pending") != "pending":
        return redirect(url_for("customer.view_nq", nq_id=nq_id))
    decision = request.form.get("decision")
    if decision not in ("accepted", "rejected"):
        return "Invalid decision", 400
    disposition["acceptanceStatus"] = decision
    disposition["_statusUpdatedBy"] = "Customer"
    workflow.save_and_publish(
        nq_id,
        nq,
        kind="DISPOSITION_STATUS_UPDATED",
        message=f"Customer {decision} a disposition.",
        on_progress=_send_progress_disposition,
    )
    return redirect(url_for("customer.view_nq", nq_id=nq_id))


@customer_bp.route("/nq/<string:nq_id>/create_containment", methods=["POST"])
@login_required
def create_containment(nq_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    reference_files = upload_many(
        CONTAINMENT_FILES_DIR,
        nq_id,
        request.files.getlist("referenceFile"),
        "pdf",
        "customer.serve_containment_file",
    )
    reference_file = reference_files[0] if reference_files else None
    nq.setdefault("ContainmentActions", []).append(
        build_containment_dict(
            nq_id, default_action_party="Customer", reference_file=reference_file
        )
    )
    nq["NonQualityHeader"]["nonQualityLastUpdateDate"] = datetime.now().isoformat()
    workflow.save_and_publish(
        nq_id,
        nq,
        kind="CONTAINMENT_ADDED",
        message="Customer created a new containment action.",
        on_progress=_send_progress_disposition,
    )
    return redirect(url_for("customer.view_nq", nq_id=nq_id))


@customer_bp.route("/nq/<string:nq_id>/containment/<string:action_id>")
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
        back_url=url_for("customer.view_nq", nq_id=nq_id),
    )


@customer_bp.route("/nq/<string:nq_id>/edit", methods=["GET", "POST"])
@login_required
def edit_nq(nq_id):
    nq = db.get_nq(nq_id)
    if nq is None:
        return "Invalid NQ ID", 404
    if request.method == "GET":
        return render_template("edit_nq.html", nq=nq)

    header = nq["NonQualityHeader"]
    header["nonQualityTitle"] = request.form.get("nonQualityTitle")
    header["nonQualityStatus"] = request.form.get("nonQualityStatus")
    header["customerComment"] = request.form.get("customerComment")
    header["nonQualityLastUpdateDate"] = datetime.now().isoformat()

    desc = nq["NonQualityDescription"]
    desc["problemShortDescription"] = request.form.get("problemShortDescription")
    desc["problemLongDescription"] = request.form.get("problemLongDescription")
    desc["issueGroup"] = request.form.get("issueGroup")
    desc["issueCode"] = request.form.get("issueCode")
    desc["safetyRelated"] = request.form.get("safetyRelated") == "on"

    remove_image_urls = set(request.form.getlist("removeImage"))
    remove_document_urls = set(request.form.getlist("removeDocument"))
    kept_images = [
        img
        for img in (desc.get("defectImage") or [])
        if img.get("url") not in remove_image_urls
    ]
    kept_documents = [
        doc
        for doc in (desc.get("defectDocument") or [])
        if doc.get("url") not in remove_document_urls
    ]
    for url in remove_image_urls:
        delete_upload(DEFECT_IMAGES_DIR, nq_id, url)
    for url in remove_document_urls:
        delete_upload(DEFECT_DOCUMENTS_DIR, nq_id, url)

    new_images = upload_many(
        DEFECT_IMAGES_DIR,
        nq_id,
        request.files.getlist("defectImage"),
        "jpg",
        "customer.serve_defect_image",
    )
    new_documents = upload_many(
        DEFECT_DOCUMENTS_DIR,
        nq_id,
        request.files.getlist("defectDocument"),
        "pdf",
        "customer.serve_defect_document",
    )
    desc["defectImage"] = kept_images + new_images
    desc["defectDocument"] = kept_documents + new_documents

    disc = nq["NonQualityDiscovery"]
    for key in (
        "stepOfProduction",
        "msn",
        "versionOfAircraft",
        "ataSection",
        "detectedHow",
        "detectedWhen",
        "detectedWhere",
        "detectedByWhom",
    ):
        disc[key] = request.form.get(key)

    scope = nq["ProductScope"]
    for key in (
        "airlineCustomer",
        "finalCustomer",
        "commodity",
        "subCommodity",
        "program",
    ):
        scope[key] = request.form.get(key)

    parts = nq.setdefault("PartIdentification", [{}]) or [{}]
    part = parts[0]
    part["customerPartNumber"] = request.form.get("customerPartNumber")
    part["customerPartName"] = request.form.get("customerPartName")
    part["partClass"] = request.form.get("partClass")
    part["affectedQuantity"] = request.form.get("NonQualityQuantity")
    part["traceabilityType"] = request.form.get("traceabilityType")
    part["traceabilityNumber"] = request.form.get("traceabilityNumber")
    part["partDigitalNameplate"] = request.form.get("DigitalNameplate") or ""
    nq["PartIdentification"] = parts

    po = nq["ImpactedPurchaseOrder"]
    po["affectedPurchaseOrderNumber"] = request.form.get("affectedPurchaseOrderNumber")
    po["purchaseOrderPositionNumber"] = request.form.get("purchaseOrderPositionNumber")

    site = nq["CollaborationPartners"]["CustomerSite"]
    for key in (
        "customerACAGECode",
        "customerGroupName",
        "customerOrganizationName",
        "customerPlantCode",
        "customerPlantName",
    ):
        site[key] = request.form.get(key)

    workflow.save_and_publish(
        nq_id,
        nq,
        kind="NQ_UPDATED",
        message="Customer updated the Non-Quality report.",
        on_progress=_send_progress_nq,
    )
    return redirect(url_for("customer.view_nq", nq_id=nq_id))


# --- real-time progress stream (queue-driven, works for both mock and EDC) --
@customer_bp.route("/progress_nq")
@login_required
def progress_stream_nq():
    def gen():
        try:
            while True:
                try:
                    data = _nq_progress.get(timeout=30)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("step") == data.get("total", 5):
                        break
                except Empty:
                    # Keepalive comment so the browser doesn't drop the connection.
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass

    return Response(gen(), mimetype="text/event-stream")


@customer_bp.route("/progress_disposition")
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


@customer_bp.route("/progress_pull")
@login_required
def progress_stream_pull():
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
