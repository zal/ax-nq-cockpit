# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""AAS instance ↔ persistent nq dict conversion, driven by the vendored model (`assets/model/*.aas.json`).
"""

import copy
import json
import mimetypes
import os
from typing import Any

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "model")
_ENV_CACHE: dict = {}


def _load_env(name: str) -> dict:
    """Load a vendored AAS environment file (ShareNonQuality, Disposition,
    ContainmentAction)."""
    if name not in _ENV_CACHE:
        with open(os.path.join(_MODEL_DIR, f"{name}.aas.json"), "r") as f:
            _ENV_CACHE[name] = json.load(f)
    return _ENV_CACHE[name]


def _load_template(name: str) -> dict:
    """The submodel template out of an environment file."""
    submodel = _load_env(name)["submodels"][0]
    return {"submodels": [submodel]}


def _english(entries: list) -> str:
    for entry in entries or []:
        if entry.get("language") == "en" and entry.get("text"):
            return entry["text"]
    return ""


def load_field_info() -> dict:
    """idShort -> English definition, from the vendored concept descriptions."""
    info: dict = {}
    for name in ("ShareNonQuality", "Disposition", "ContainmentAction"):
        for cd in _load_env(name).get("conceptDescriptions", []) or []:
            id_short = cd.get("idShort")
            if not id_short or id_short in info:
                continue
            definition = ""
            for spec in cd.get("embeddedDataSpecifications", []) or []:
                definition = _english(
                    spec.get("dataSpecificationContent", {}).get("definition")
                )
                if definition:
                    break
            definition = definition or _english(cd.get("description"))
            if definition:
                info[id_short] = definition
    return info


def _coerce_file_value(source_value: Any) -> str:
    if isinstance(source_value, dict):
        return source_value.get("url_aas") or source_value.get("url") or ""
    if isinstance(source_value, list):
        return _coerce_file_value(source_value[0]) if source_value else ""
    if isinstance(source_value, str):
        return source_value
    return ""


def _to_aas_value(element: dict, value: Any) -> Any:
    value_type = element.get("valueType", "")
    if value_type == "xs:anyURI":
        return _coerce_file_value(value)
    if value_type == "xs:dateTime" and isinstance(value, str) and len(value) == 10:
        return value + "T00:00:00"
    return value


def _populate_list_item(item_template: dict, item: Any) -> dict:
    child = copy.deepcopy(item_template)
    child.pop("idShort", None)
    if child.get("modelType") == "SubmodelElementCollection":
        _populate_elements(
            child.get("value", []), item if isinstance(item, dict) else {}
        )
    else:
        child["value"] = _to_aas_value(child, item)
    return child


def _populate_elements(elements: list, source: dict) -> None:
    for el in elements or []:
        id_short = el.get("idShort")
        if id_short is None:
            continue
        model_type = el.get("modelType")

        if model_type == "SubmodelElementCollection":
            sub = source.get(id_short)
            sub_source = sub if isinstance(sub, dict) else source
            _populate_elements(el.get("value", []), sub_source)
            continue

        if model_type == "SubmodelElementList":
            item_template = (el.get("value") or [{}])[0]
            items = source.get(id_short) or []
            el["value"] = [_populate_list_item(item_template, item) for item in items]
            continue

        if id_short not in source:
            continue
        el["value"] = _to_aas_value(el, source[id_short])


def populate_submodel(template: dict, source: dict) -> dict:
    populated = copy.deepcopy(template)
    submodel = populated.get("submodels", [{}])[0]
    submodel.pop("kind", None)  # the vendored file is kind=Template; instances are not
    _populate_elements(submodel.get("submodelElements", []), source)
    return populated


def _uri_to_attachment(value: str) -> dict | None:
    if not value or not isinstance(value, str):
        return None
    filename = value.rstrip("/").rsplit("/", 1)[-1]
    return {
        "url": value,
        "url_aas": value,
        "filename": filename,
        "content_type": mimetypes.guess_type(filename)[0] or "",
    }


_UPLOADED_FILE_FIELDS = {"referenceFile"}


def _parse_list_item(item: dict) -> Any:
    if item.get("modelType") == "SubmodelElementCollection":
        return _parse_elements(item.get("value", []))
    if item.get("valueType") == "xs:anyURI":
        return _uri_to_attachment(item.get("value"))
    return item.get("value")


def _parse_elements(elements: list) -> dict:
    out: dict = {}
    for el in elements or []:
        id_short = el.get("idShort")
        if id_short is None:
            continue
        model_type = el.get("modelType")

        if model_type == "SubmodelElementCollection":
            out[id_short] = _parse_elements(el.get("value", []))
        elif model_type == "SubmodelElementList":
            out[id_short] = [
                parsed
                for item in (el.get("value", []) or [])
                if isinstance(item, dict)
                and not item.get("idShort")  # skip an unpopulated template child
                and (parsed := _parse_list_item(item)) is not None
            ]
        elif id_short in _UPLOADED_FILE_FIELDS and el.get("valueType") == "xs:anyURI":
            out[id_short] = _uri_to_attachment(el.get("value"))
        else:
            out[id_short] = el.get("value")
    return out


def parse_submodel(submodel: dict) -> dict:
    return _parse_elements(submodel.get("submodelElements", []))


def create_aas_instance_share_nq(nq: dict) -> dict:
    return populate_submodel(_load_template("ShareNonQuality"), nq)


def create_aas_instance_disposition(disposition: dict) -> dict:
    return populate_submodel(_load_template("Disposition"), disposition)


def create_aas_instance_immediate_containment(containment: dict) -> dict:
    return populate_submodel(_load_template("ContainmentAction"), containment)


def merge_remote_authored(
    local_items: list, remote_items: list, field: str, remote_author: str
) -> list:
    """Replace items whose {field}=={remote_author} in `local_items` with `remote_items`.

    Used on both sides of the dataspace exchange: when pulling a counterpart's
    bundle, the pulled list is the authoritative view of items authored by them,
    but anything locally authored must survive the merge.
    """
    own = [it for it in (local_items or []) if it.get(field) != remote_author]
    sanitized_remote = []
    for it in remote_items or []:
        if isinstance(it, dict):
            it[field] = remote_author
        sanitized_remote.append(it)
    return own + sanitized_remote


def parse_aas_bundle_to_nq(bundle: dict) -> dict:
    """Parse a multi-submodel envelope ({"submodels": [share_nq, disp1, ..., ic1, ...]})
    into the AAS-aligned persistent nq dict. Dispositions and ContainmentActions
    accumulate in their respective arrays in submodel-id order.
    """
    submodels = bundle.get("submodels", []) or []

    nq: dict = {}
    dispositions: list = []
    containments: list = []

    for sm in submodels:
        id_short = sm.get("idShort", "") or ""
        sm_id = sm.get("id", "") or ""
        if id_short.startswith("ShareNonQuality") or ":sm:ShareNonQuality" in sm_id:
            nq = parse_submodel(sm)
        elif id_short.startswith("Disposition") or ":sm:Disposition" in sm_id:
            dispositions.append(parse_submodel(sm))
        elif (
            id_short.startswith("ContainmentAction") or ":sm:ContainmentAction" in sm_id
        ):
            containments.append(parse_submodel(sm))

    if dispositions:
        nq["Disposition"] = dispositions
    if containments:
        nq["ContainmentActions"] = containments
    return nq
