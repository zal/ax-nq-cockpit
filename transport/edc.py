# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Eclipse Dataspace Connector (EDC) transport.

Implements the three Transport methods against the EDC management API v3.
Select by switching the mode to "edc" in the EDC Management Cockpit UI.

Provider side (offer):
  1. POST /management/v3/assets            — register data endpoint
  2. POST /management/v3/policydefinitions — open access policy
  3. POST /management/v3/contractdefinitions

Consumer side (pull):
  1. POST /management/v3/catalog/request   — find offer id for the asset
  2. POST /management/v3/contractnegotiations + poll → FINALIZED
  3. POST /management/v3/transferprocesses + poll → STARTED
  4. GET  /management/v3/edrs/{id}/dataaddress → authorization token + endpoint
  5. GET  {endpoint}                        — fetch the bundle JSON

notify: simple HTTP POST to the partner app's notification endpoint
        (same shape as MockTransport; the EDC only handles data transfer).
"""

import time
from urllib.parse import urlparse

import requests

import config
from db import db
from transport.base import Transport
from utils.edc_utils import (
    create_asset,
    create_contract,
    create_policy,
    fetch_data,
    fetch_provider_catalog,
    negotiate_contract,
    start_transfer,
)


class EdcTransport(Transport):
    name = "edc"

    def _settings(self):
        s = db.get_connector_settings()
        if not s.get("connector_hostname"):
            raise RuntimeError(
                "EDC connector not configured. Set the Connector Base URL in the "
                "EDC Management Cockpit before switching to EDC transport."
            )
        return s

    def _headers(self, s):
        h = {"Content-Type": "application/json"}
        if s.get("x_api_key"):
            h["X-Api-Key"] = s["x_api_key"]
        return h

    def _partner_info(self):
        """Return the first trusted partner"""
        partners = db.get_trusted_partners()
        if not partners:
            raise RuntimeError(
                "No trusted partner configured. Add a partner in the EDC Management "
                "Cockpit (Add Partner) before using EDC transport."
            )
        return partners[0]

    @staticmethod
    def _identity_netloc(hostname_or_did):
        """Return the netloc portion of a did:web DID or a plain hostname/URL."""
        if hostname_or_did.startswith("did:web:"):
            return hostname_or_did[len("did:web:") :]
        parsed = urlparse(hostname_or_did)
        return parsed.netloc or hostname_or_did

    # ── provider side ────────────────────────────────────────────────────────

    def offer(
        self, asset_id, nq_id, bundle, allowed_party, on_progress=None, is_new=True
    ):
        """Register asset + policy + contract definition in own EDC connector."""

        def _p(step, msg):
            if on_progress:
                on_progress(step, msg)

        # Store locally so our HTTP endpoint can serve the bundle to the EDC
        # data plane when it proxies the consumer's pull request.
        db.save_offer(asset_id, nq_id, allowed_party, bundle)

        if not is_new:
            _p(2, "Updated Asset")
            return

        s = self._settings()
        h = self._headers(s)
        mgmt = s["connector_hostname"]
        data_url = f"{config.OWN_URL}/api/dataspace/data/{asset_id}"

        create_asset(
            connector_hostname=mgmt,
            additional_headers=h,
            asset_id=asset_id,
            data_address_base_url=data_url,
            data_address_headers={"X-Dataspace-Secret": config.DATASPACE_SECRET},
        )
        _p(2, "Created Asset")

        policy_id = f"policy-{asset_id}"

        resp = create_policy(
            connector_hostname=mgmt, additional_headers=h, policy_id=policy_id
        )

        _p(3, "Created Policy")

        # 3. Contract definition — binds the policy to the specific asset.
        contract_id = f"contract-{asset_id}"

        create_contract(
            connector_hostname=mgmt,
            additional_headers=h,
            contract_id=contract_id,
            policy_response_id=resp["@id"],
            asset_id=asset_id,
        )

        _p(4, "Created Contract")

    def notify(self, partner_url, asset_id, nq_id, kind, message=""):
        """Notify the partner app via plain HTTP (same shape as MockTransport).
        The EDC only handles the data transfer.
        """
        h = {"Content-Type": "application/json"}
        if config.DATASPACE_SECRET:
            h["X-Dataspace-Secret"] = config.DATASPACE_SECRET
        r = requests.post(
            f"{partner_url}/api/dataspace/notifications",
            json={
                "asset_id": asset_id,
                "nq_id": nq_id,
                "kind": kind,
                "message": message,
            },
            headers=h,
            timeout=10,
        )
        r.raise_for_status()

    # ── consumer side ────────────────────────────────────────────────────────

    def pull(self, partner_url, asset_id, on_progress=None):
        """Pull asset through own EDC connector.

        Flow: catalog request → contract negotiation (poll FINALIZED)
              → transfer process (poll STARTED) → EDR → GET data endpoint.
        """

        def _p(step, msg):
            if on_progress:
                on_progress(step, msg, 4)

        s = self._settings()
        h = self._headers(s)
        mgmt = s["connector_hostname"]

        partner = self._partner_info()
        partner_connector = partner.get("edc_hostname") or ""
        if not partner_connector:
            label = partner.get("label") or partner["edc_connector_did"]
            raise RuntimeError(
                f"Partner {label!r} has no EDC hostname configured. "
                "Update the partner in the EDC Management Cockpit."
            )
        partner_identity = self._identity_netloc(partner["edc_connector_did"])

        agreement_id = db.get_agreement(asset_id, config.ROLE)
        if agreement_id:
            catalog = fetch_provider_catalog(
                connector_hostname=mgmt,
                counter_party_hostname=partner_connector,
                counter_party_identity_hostname=partner_identity,
                additional_headers=h,
            )

            _p(1, "Queried catalog")
            time.sleep(1)

            _p(2, "Using existing contract")
            _, transfer_process_id = start_transfer(
                contract={"contractAgreementId": agreement_id},
                connector_hostname=mgmt,
                counter_party_connector_hostname=partner_connector,
                additional_header=h,
            )
            _p(3, "Started transfer")
            data = fetch_data(
                transfer_process_id=transfer_process_id,
                connector_hostname=mgmt,
                counter_party_connector_hostname=partner_connector,
                additional_header=h,
            )
            _p(4, "Fetched data")
            return data.json()

        else:
            catalog = fetch_provider_catalog(
                connector_hostname=mgmt,
                counter_party_hostname=partner_connector,
                counter_party_identity_hostname=partner_identity,
                additional_headers=h,
            )

            _p(1, "Queried catalog")

            datasets = catalog["dcat:dataset"]
            if isinstance(datasets, dict):
                datasets = [datasets]
            policy_id = None
            for ds in datasets:
                if ds["@id"] == asset_id:
                    policy_id = ds["odrl:hasPolicy"]["@id"]
                    break
            if policy_id is None:
                raise RuntimeError(f"asset {asset_id} not found in provider catalog")

            contract = negotiate_contract(
                policy_id=policy_id,
                counter_party_identity_hostname=partner_identity,
                asset_target=asset_id,
                connector_hostname=mgmt,
                counter_party_connector_hostname=partner_connector,
                additional_header=h,
            )
            db.save_agreement(asset_id, config.ROLE, contract["contractAgreementId"])
            _p(2, "Negotiated contract")

            _, transfer_process_id = start_transfer(
                contract=contract,
                connector_hostname=mgmt,
                counter_party_connector_hostname=partner_connector,
                additional_header=h,
            )

            _p(3, "Started transfer")

            data = fetch_data(
                transfer_process_id=transfer_process_id,
                connector_hostname=mgmt,
                counter_party_connector_hostname=partner_connector,
                additional_header=h,
            )
            _p(4, "Fetched data")
            return data.json()
