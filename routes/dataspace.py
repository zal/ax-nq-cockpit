# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Mock pull-based dataspace endpoints (the EDC stand-in).

The endpoints map 1:1 onto the real EDC steps:

  POST /api/dataspace/notifications  <- partner says "asset available"
  GET  /api/dataspace/catalog        -> asset ids offered to the caller
  POST /api/dataspace/negotiate      -> a (mock, instant) contract agreement
  GET  /api/dataspace/data/<asset>   -> the asset payload, given a valid agreement
"""

from flask import Blueprint, abort, jsonify, request

import config
from basyx_mirror import client as basyx_client
from db import db
from workflow import handle_notification

dataspace_bp = Blueprint("dataspace", __name__, url_prefix="/api/dataspace")


@dataspace_bp.before_request
def _check_secret():
    if (
        config.DATASPACE_SECRET
        and request.headers.get("X-Dataspace-Secret") != config.DATASPACE_SECRET
    ):
        abort(403)


@dataspace_bp.post("/notifications")
def notifications():
    body = request.get_json(force=True, silent=True) or {}
    handle_notification(
        body.get("asset_id"),
        body.get("nq_id"),
        body.get("kind", "update"),
        body.get("message", ""),
    )
    return jsonify({"status": "pulled"})


@dataspace_bp.get("/catalog")
def catalog():
    party = request.args.get("party", "")
    return jsonify({"assets": db.list_offer_ids_for(party)})


@dataspace_bp.post("/negotiate")
def negotiate():
    body = request.get_json(force=True, silent=True) or {}
    asset_id = body.get("asset_id")
    party = body.get("party")
    offer = db.get_offer(asset_id)
    if not offer or offer["allowed_party"] != party:
        abort(404)
    return jsonify({"agreement_id": f"agr_{asset_id}_{party}"})


@dataspace_bp.get("/data/<asset_id>")
def data(asset_id):
    offer = db.get_offer(asset_id)
    if not offer:
        abort(404)
    party = request.args.get("party")
    agreement = request.args.get("agreement")
    if party is not None or agreement is not None:
        if offer["allowed_party"] != party or agreement != f"agr_{asset_id}_{party}":
            abort(403)
    bundle = basyx_client.read_owned_bundle(offer["nq_id"])
    return jsonify(bundle)
