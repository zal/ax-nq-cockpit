# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""BaSyx AAS environment client — each side's authoritative store for the
submodels it OWNS, and the surface a partner pulls from.
"""

import base64

import requests

import config

_SHELL_ID = "urn:aerospace-x:nq:{nq_id}:shell"
_ASSET_ID = "urn:aerospace-x:nq:{nq_id}:asset"
_TIMEOUT = 5


def _b64(value):
    """base64url without padding — how BaSyx expects ids in path params."""
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def mirror_bundle(nq_id, bundle):
    """Push the shell + every submodel in `bundle` into the AAS environment."""
    if not config.BASYX_ENABLED:
        return
    base = config.BASYX_ENV_URL
    try:
        _ensure_shell(base, nq_id)
        for submodel in bundle.get("submodels", []):
            if not submodel.get("id"):
                continue
            _upsert_submodel(base, submodel)
            _ensure_submodel_ref(base, nq_id, submodel["id"])
    except Exception as exc:
        print(f"[basyx] mirror failed for {nq_id}: {exc}")


def _ensure_shell(base, nq_id):
    shell_id = _SHELL_ID.format(nq_id=nq_id)
    if (
        requests.get(f"{base}/shells/{_b64(shell_id)}", timeout=_TIMEOUT).status_code
        == 200
    ):
        return
    shell = {
        "modelType": "AssetAdministrationShell",
        "id": shell_id,
        "idShort": f"NQ_{nq_id}".replace("-", "_"),
        "assetInformation": {
            "assetKind": "Instance",
            "globalAssetId": _ASSET_ID.format(nq_id=nq_id),
        },
        "submodels": [],
    }
    requests.post(f"{base}/shells", json=shell, timeout=_TIMEOUT)


def _upsert_submodel(base, submodel):
    sm_b64 = _b64(submodel["id"])
    resp = requests.put(f"{base}/submodels/{sm_b64}", json=submodel, timeout=_TIMEOUT)
    if resp.status_code not in (200, 204):
        requests.post(f"{base}/submodels", json=submodel, timeout=_TIMEOUT)


def _ensure_submodel_ref(base, nq_id, sm_id):
    shell_id = _SHELL_ID.format(nq_id=nq_id)
    ref = {"type": "ModelReference", "keys": [{"type": "Submodel", "value": sm_id}]}
    requests.post(
        f"{base}/shells/{_b64(shell_id)}/submodel-refs", json=ref, timeout=_TIMEOUT
    )


# --- read back (the pull source) -------------------------------------------
def _submodel_ids(base, nq_id):
    """Submodel ids referenced by the NQ shell (empty if the shell is absent)."""
    shell_id = _SHELL_ID.format(nq_id=nq_id)
    resp = requests.get(f"{base}/shells/{_b64(shell_id)}", timeout=_TIMEOUT)
    if resp.status_code != 200:
        return []
    ids = []
    for ref in resp.json().get("submodels", []) or []:
        keys = ref.get("keys", [])
        if keys:
            ids.append(keys[-1].get("value"))
    return [i for i in ids if i]


def read_owned_bundle(nq_id):
    """Read this side's owned submodels for `nq_id` back out of BaSyx as a
    transport bundle ({"nq_id", "submodels": [...]}) — the same envelope shape
    aas_utils.parse_aas_bundle_to_nq consumes."""
    if not config.BASYX_ENABLED:
        return None
    base = config.BASYX_ENV_URL
    try:
        submodels = []
        for sm_id in _submodel_ids(base, nq_id):
            resp = requests.get(f"{base}/submodels/{_b64(sm_id)}", timeout=_TIMEOUT)
            if resp.status_code == 200:
                submodels.append(resp.json())
        return {"nq_id": nq_id, "submodels": submodels} if submodels else None
    except Exception as exc:
        print(f"[basyx] read failed for {nq_id}: {exc}")
        return None
