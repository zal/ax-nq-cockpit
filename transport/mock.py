# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Mock pull-based transport: plain HTTP between the two app containers.
"""

import requests

import config
from db import db
from transport.base import Transport


class MockTransport(Transport):
    name = "mock"

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if config.DATASPACE_SECRET:
            headers["X-Dataspace-Secret"] = config.DATASPACE_SECRET
        return headers

    # --- provider side -----------------------------------------------------
    def offer(
        self, asset_id, nq_id, bundle, allowed_party, on_progress=None, is_new=True
    ):
        db.save_offer(asset_id, nq_id, allowed_party, bundle)
        if not on_progress:
            return
        if is_new:
            on_progress(2, "Created Asset")
            on_progress(3, "Created Policy")
            on_progress(4, "Created Contract")
        else:
            on_progress(2, "Updated Asset")

    def notify(self, partner_url, asset_id, nq_id, kind, message=""):
        resp = requests.post(
            f"{partner_url}/api/dataspace/notifications",
            json={
                "asset_id": asset_id,
                "nq_id": nq_id,
                "kind": kind,
                "message": message,
            },
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()

    # --- consumer side -----------------------------------------------------
    def pull(self, partner_url, asset_id, on_progress=None):
        def _p(step, msg):
            if on_progress:
                on_progress(step, msg, 4)

        # 1. catalog fetch
        catalog = requests.get(
            f"{partner_url}/api/dataspace/catalog",
            params={"party": config.ROLE},
            headers=self._headers(),
            timeout=10,
        ).json()
        if asset_id not in catalog.get("assets", []):
            raise RuntimeError(
                f"asset {asset_id!r} not offered to {config.ROLE} in partner catalog"
            )
        _p(1, "Queried catalog")

        # 2. negotiate — reuse a prior agreement for this asset if one already exists
        agreement_id = db.get_agreement(asset_id, config.ROLE)
        if agreement_id:
            _p(2, "Using existing contract")
        else:
            negotiation = requests.post(
                f"{partner_url}/api/dataspace/negotiate",
                json={"asset_id": asset_id, "party": config.ROLE},
                headers=self._headers(),
                timeout=10,
            ).json()
            agreement_id = negotiation["agreement_id"]
            db.save_agreement(asset_id, config.ROLE, agreement_id)
            _p(2, "Negotiated contract")

        # 3. transfer + fetch — exchange the agreement for the payload
        _p(3, "Started transfer")
        data = requests.get(
            f"{partner_url}/api/dataspace/data/{asset_id}",
            params={"agreement": agreement_id, "party": config.ROLE},
            headers=self._headers(),
            timeout=10,
        ).json()
        _p(4, "Fetched data")
        return data
