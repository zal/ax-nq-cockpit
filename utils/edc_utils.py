# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

import json
import os
import time

import requests

from utils import file_utils, http_request_utils

BASE_PATH = os.path.join(os.path.dirname(__file__), "..", "resources")


def _load_json(filename):
    """Read a request template from resources/.

    Unlike file_utils.read_json this raises instead of calling exit(1), so it
    is safe to call from inside a Flask request.
    """
    with open(os.path.join(BASE_PATH, filename)) as f:
        return json.load(f)


def create_asset(
    connector_hostname: str,
    additional_headers: dict,
    asset_id: str,
    data_address_base_url: str,
    data_address_headers: dict = None,
):
    url = f"{connector_hostname}/management/v3/assets"
    headers = {"Content-Type": "application/json"}
    if additional_headers != None:
        headers.update(additional_headers)
    json_file_path = f"{BASE_PATH}/create-asset.json"
    payload = file_utils.read_json(json_file_path=json_file_path)
    payload["@id"] = asset_id
    payload["dataAddress"]["baseUrl"] = data_address_base_url
    if data_address_headers:
        for k, v in data_address_headers.items():
            payload["dataAddress"][f"header:{k}"] = v
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an error for bad status
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Failed to create asset: {e}")
        return response


def create_policy(connector_hostname: str, additional_headers: dict, policy_id: str):
    url = f"{connector_hostname}/management/v3/policydefinitions"
    headers = {"Content-Type": "application/json"}
    if additional_headers != None:
        headers.update(additional_headers)
    json_file_path = f"{BASE_PATH}/create-policy.json"
    payload = file_utils.read_json(json_file_path=json_file_path)
    payload["@id"] = policy_id
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an error for bad status
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Failed to create policy: {e}")
        return response


def create_contract(
    connector_hostname: str,
    additional_headers: dict,
    contract_id: str,
    policy_response_id: str,
    asset_id: str,
):
    url = f"{connector_hostname}/management/v3/contractdefinitions"
    headers = {"Content-Type": "application/json"}
    if additional_headers != None:
        headers.update(additional_headers)
    json_file_path = f"{BASE_PATH}/create-contract.json"
    payload = file_utils.read_json(json_file_path=json_file_path)
    payload["@id"] = contract_id
    payload["accessPolicyId"] = policy_response_id
    payload["contractPolicyId"] = policy_response_id
    payload["assetsSelector"][0]["operandRight"] = asset_id
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an error for bad status
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Failed to create contract: {e}")
        return response


def fetch_provider_catalog(
    connector_hostname: str,
    counter_party_hostname: str,
    counter_party_identity_hostname: str,
    additional_headers: dict = None,
):
    url = f"{connector_hostname}/management/v3/catalog/request"
    headers = {"Content-Type": "application/json"}
    if additional_headers != None:
        headers.update(additional_headers)
    json_file_path = f"{BASE_PATH}/catalog_request.json"
    payload = file_utils.read_json(json_file_path=json_file_path)
    payload["counterPartyId"] = f"did:web:{counter_party_identity_hostname}"
    payload["counterPartyAddress"] = f"{counter_party_hostname}/api/v1/dsp"
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an error for bad status
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch catalog: {e}")
        return response


def fetch_own_catalog(
    connector_hostname: str, identity_netloc: str, additional_headers: dict = None
):
    """POST /management/v3/catalog/request for the connector's own catalog.

    Returns the parsed JSON dict on success, or a requests.Response on HTTP
    error so the caller can inspect status/body. On connection-level errors
    (no response) the exception propagates.
    """
    url = f"{connector_hostname}/management/v3/catalog/request"
    headers = {"Content-Type": "application/json"}
    if additional_headers != None:
        headers.update(additional_headers)
    payload = _load_json("catalog_request.json")
    payload["counterPartyId"] = f"did:web:{identity_netloc}"
    payload["counterPartyAddress"] = f"{connector_hostname}/api/v1/dsp"
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        if getattr(e, "response", None) is not None:
            return e.response
        raise


def list_assets(connector_hostname: str, additional_headers: dict = None):
    """POST /management/v3/assets/request — used to check connector liveness.

    Returns (json, status_code); raises on error.
    """
    url = f"{connector_hostname}/management/v3/assets/request"
    headers = {"Content-Type": "application/json"}
    if additional_headers != None:
        headers.update(additional_headers)
    payload = _load_json("list_assets.json")
    response = requests.post(url, json=payload, headers=headers, timeout=5)
    response.raise_for_status()
    return response.json(), response.status_code


def negotiate_contract(
    policy_id,
    counter_party_identity_hostname,
    asset_target,
    connector_hostname=None,
    counter_party_connector_hostname: str = None,
    additional_header=None,
):  #
    url = f"{connector_hostname}/management/v3/contractnegotiations"
    # Read the JSON file
    json_file_path = f"{BASE_PATH}/contract_neg.json"
    payload = file_utils.read_json(json_file_path=json_file_path)
    payload["policy"]["@id"] = policy_id
    payload["policy"]["target"] = asset_target
    payload["policy"]["assigner"] = f"did:web:{counter_party_identity_hostname}"
    payload["counterPartyAddress"] = f"{counter_party_connector_hostname}/api/v1/dsp"

    headers = {"Content-Type": "application/json"}
    if additional_header != None:
        headers.update(additional_header)
    response = http_request_utils.get_post(url, payload=payload, header=headers)
    contract_negotiation_id = response["@id"]
    url = f"{url}/{contract_negotiation_id}"
    restart_timer = 20
    while 1:
        if restart_timer == 0:
            return
        else:
            response = http_request_utils.get_post(url, header=headers)
            if response["state"] == "FINALIZED" or response["state"] == "TERMINATED":
                return response
            time.sleep(1)
        restart_timer -= 1


def start_transfer(
    contract,
    connector_hostname,
    counter_party_connector_hostname,
    additional_header=None,
):
    url = f"{connector_hostname}/management/v3/transferprocesses"
    # Read the JSON file
    json_file_path = f"{BASE_PATH}/start_transfer.json"
    payload = file_utils.read_json(json_file_path=json_file_path)
    payload["contractId"] = contract["contractAgreementId"]

    if counter_party_connector_hostname != None:
        payload[
            "counterPartyAddress"
        ] = f"{counter_party_connector_hostname}/api/v1/dsp"
    response = http_request_utils.get_post(
        url, payload=payload, header=additional_header
    )
    transfer_process_id = response["@id"]
    url = f"{url}/{transfer_process_id}"

    while 1:
        response = http_request_utils.get_post(url, header=additional_header)
        if response["state"] == "STARTED":
            return response, transfer_process_id
        elif response["state"] == "TERMINATED":
            raise Exception("Transfer process terminated unexpectedly.")
        time.sleep(1)


def fetch_data(
    transfer_process_id,
    connector_hostname,
    counter_party_connector_hostname,
    additional_header=None,
):
    url = f"{connector_hostname}/management/v3/edrs/{transfer_process_id}/dataaddress"
    response = http_request_utils.get_post(url, header=additional_header)
    print(f"Data Response:{response}")
    url = f"{counter_party_connector_hostname}/api/public"
    header = {"Authorization": response["authorization"]}
    header.update(additional_header)
    return http_request_utils.get_post(url, header=header)
