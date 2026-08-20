# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Role-agnostic NQ workflow shared by the HTTP routes and the dataspace pull.
"""

import config
import utils.aas_utils as aas_utils
from basyx_mirror import client as basyx_client
from db import db
from transport.base import get_transport

_SM_ID = "urn:aerospace-x:nq:{nq_id}:sm:{kind}"


def asset_id_for(nq_id):
    return f"asset_nq_{nq_id}"


def _sm_id(kind, nq_id, suffix=None):
    base = _SM_ID.format(kind=kind, nq_id=nq_id)
    return f"{base}:{suffix}" if suffix is not None else base


def build_offer_bundle(nq_id, nq, author_role):
    """Author-scoped bundle: only the submodels THIS side authors. It is what we
    mirror into our OWN BaSyx (each side stores just its own work) AND what the
    partner pulls. The consumer merges it without clobbering its own work
    (a customer pulling the supplier's bundle keeps its own dispositions, etc.).
    The customer owns ShareNonQuality; both sides may author dispositions/actions.
    idShort/id are stamped per instance so submodels don't collide and stay
    parseable by aas_utils.parse_aas_bundle_to_nq.
    """
    author = author_role.capitalize()
    submodels = []

    if author_role == "customer":
        share = aas_utils.create_aas_instance_share_nq(nq)["submodels"][0]
        share["id"] = _sm_id("ShareNonQuality", nq_id)
        share["idShort"] = "ShareNonQuality"
        submodels.append(share)

    for i, disposition in enumerate(nq.get("Disposition", []) or []):
        if (
            disposition.get("dispositionCreator") == author
        ):
            sm = aas_utils.create_aas_instance_disposition(disposition)["submodels"][0]
            sm["id"] = _sm_id("Disposition", nq_id, f"{author_role}-{i}")
            sm["idShort"] = f"Disposition_{author_role}_{i}"
            submodels.append(sm)

    for containment in nq.get("ContainmentActions", []) or []:
        if containment.get("actionParty") == author:
            action_id = containment.get("actionId") or str(len(submodels))
            sm = aas_utils.create_aas_instance_immediate_containment(containment)[
                "submodels"
            ][0]
            sm["id"] = _sm_id("ContainmentAction", nq_id, action_id)
            sm["idShort"] = f"ContainmentAction_{action_id}"
            submodels.append(sm)

    return {"nq_id": nq_id, "submodels": submodels}


def _mirror_owned(nq_id, nq):
    """Mirror only the submodels this side owns into our BaSyx. Defect files are
    hosted by the app itself; the mirrored xs:anyURI elements carry their
    partner-reachable URLs. Skips empty owned bundles so we don't create bare
    shells for an NQ this side has not authored anything in yet."""
    owned = build_offer_bundle(nq_id, nq, config.ROLE)
    if owned["submodels"]:
        basyx_client.mirror_bundle(nq_id, owned)
    return owned


def save_and_publish(nq_id, nq, *, kind, message="", on_progress=None):
    """Persist locally, mirror our OWN submodels to BaSyx, then offer
    that author-scoped bundle + notify the partner so it can pull from our BaSyx.

    on_progress(step, message, total) is forwarded into the transport so callers
    can stream real-time EDC progress. `total` is 5 the first time this asset is
    offered to the partner (asset + policy + contract creation) or 3 on every
    later publish for the same asset (the policy/contract already exist and are
    reused — only the data endpoint is refreshed and the partner re-notified).
    """
    asset_id = asset_id_for(nq_id)
    is_new = db.get_offer(asset_id) is None
    total = 5 if is_new else 3

    def _p(step, msg):
        if on_progress:
            on_progress(step, msg, total)

    db.save_nq(nq_id, nq)
    owned = _mirror_owned(nq_id, nq)
    _p(1, "Created data endpoint URL")

    transport = get_transport()
    transport.offer(
        asset_id,
        nq_id,
        owned,
        allowed_party=config.PARTNER_ROLE,
        on_progress=_p,
        is_new=is_new,
    )

    transport.notify(config.PARTNER_URL, asset_id, nq_id, kind, message)
    _p(total, f"Notified {config.PARTNER_ROLE}")


_UPDATE_KINDS = (
    "DISPOSITION_ADDED",
    "CONTAINMENT_ADDED",
    "NQ_UPDATED",
    "DISPOSITION_STATUS_UPDATED",
)


def handle_notification(asset_id, nq_id, kind, message):
    """Consumer side: react to the partner's "asset available" notification.

    We do NOT pull here — pull-based means the consumer initiates the fetch:
      * a partner update to an NQ we already hold sets a pending flag surfaced
        on view_nq as a "Fetch update" button, and is flagged in the overview
        table (-> pull_from_partner in routes/*.fetch_update / fetch_nq_data)
      * a brand-new NQ we don't hold yet lands in the inbox with a "Fetch asset"
        button (supplier side)
      * close: applied immediately (no payload to pull)

    Both roles behave the same: whether an inbound event is an "update" or a
    "new asset" depends only on whether we already have the NQ locally, not on
    which role we are.
    """
    if kind == "NQ_CLOSED":
        nq = db.get_nq(nq_id)
        if nq and nq.get("NonQualityHeader"):
            nq["NonQualityHeader"]["nonQualityStatus"] = "CLOSED"
            db.save_nq(nq_id, nq)
        return

    nq = db.get_nq(nq_id)
    if nq and kind in _UPDATE_KINDS:
        nq["PartnerUpdatePending"] = True
        db.save_nq(nq_id, nq)
    db.add_notification(nq_id, kind, message or f"{config.PARTNER_ROLE} sent: {kind}")


def pull_from_partner(nq_id, on_progress=None):
    """Consumer side: pull the asset from the partner and merge it locally."""
    bundle = get_transport().pull(
        config.PARTNER_URL, asset_id_for(nq_id), on_progress=on_progress
    )
    return ingest(nq_id, bundle)


def ingest(nq_id, bundle):
    """Merge a pulled partner bundle into the local nq record, preserving
    locally-authored dispositions and containment actions."""
    remote = aas_utils.parse_aas_bundle_to_nq(bundle)
    local = db.get_nq(nq_id) or {}

    remote_dispositions = remote.pop("Disposition", []) or []
    remote_containments = remote.pop("ContainmentActions", []) or []

    merged = dict(local)
    merged.update(
        remote
    )  # share-level fields come from the partner (originator authors them)

    partner_author = config.PARTNER_ROLE.capitalize()
    own_role = config.ROLE.capitalize()

    # Split what the partner sent us: items they actually authored (normal
    # merge, replacing our copy of their side) vs. "boomerang" status updates —
    # one of OUR OWN dispositions, returned with an updated acceptanceStatus
    # after the partner accepted/rejected it. The latter must patch our
    # existing item in place, not appear as a new (mis-attributed) entry.
    genuine_remote = [
        d for d in remote_dispositions if d.get("dispositionCreator") != own_role
    ]
    status_patches = [
        d for d in remote_dispositions if d.get("dispositionCreator") == own_role
    ]

    merged["Disposition"] = aas_utils.merge_remote_authored(
        local.get("Disposition", []),
        genuine_remote,
        "dispositionCreator",
        partner_author,
    )

    for patch in status_patches:
        for item in merged["Disposition"]:
            if (
                item.get("dispositionCreator") == own_role
                and item.get("nonQualityId") == patch.get("nonQualityId")
                and item.get("transactionTimeStamp")
                == patch.get("transactionTimeStamp")
            ):
                item["acceptanceStatus"] = patch.get(
                    "acceptanceStatus", item.get("acceptanceStatus")
                )
                item["_statusUpdatedBy"] = partner_author
                break

    merged["ContainmentActions"] = aas_utils.merge_remote_authored(
        local.get("ContainmentActions", []),
        remote_containments,
        "actionParty",
        partner_author,
    )
    merged["PartnerUpdatePending"] = False

    if not local:
        merged["_received"] = True

    db.save_nq(nq_id, merged)
    _mirror_owned(nq_id, merged)
    return merged
