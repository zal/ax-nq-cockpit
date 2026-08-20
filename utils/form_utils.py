# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

import secrets
import string
from datetime import datetime

from flask import request

_ALPHABET = string.ascii_letters + string.digits


def generate_random_id(length=8):
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def build_disposition_dict(nq_id, *, creator):
    additional_documents = []
    for url in request.form.getlist("AdditionalDocumentUrl"):
        url = (url or "").strip()
        if url:
            additional_documents.append(
                {
                    "url": url,
                    "url_aas": url,
                    "filename": url.rsplit("/", 1)[-1],
                    "content_type": "",
                }
            )
    return {
        "nonQualityId": nq_id,
        "transactionTimeStamp": datetime.now().isoformat(),
        "dispositionCreator": creator,
        "dispositionType": request.form.get("dispositionType"),
        "decisionReason": request.form.get("decisionReason"),
        "acceptanceStatus": "pending",
        "ProposedCompletionPeriod": {
            "proposedCompletionFrom": request.form.get("proposedCompletionFrom"),
            "proposedCompletionTo": request.form.get("proposedCompletionTo"),
        },
        "ContactPersonInfo": [
            {
                "contactPartyType": creator,
                "contactPersonName": request.form.get("contactPersonName"),
                "contactPersonEmail": request.form.get("contactPersonEmail"),
                "contactPersonPhoneNumber": request.form.get(
                    "contactPersonPhoneNumber"
                ),
            }
        ],
        "Comment": {
            "commentIssuer": creator,
            "commentDate": request.form.get("commentDate")
            or datetime.now().isoformat(),
            "commentContent": request.form.get("commentContent"),
        },
        "AdditionalInformation": [
            {
                "additionalInformationText": request.form.get("AdditionalInformation"),
                "additionalDocument": additional_documents,
            }
        ],
        "RequestForMoreInformation": [
            {
                "requestDescription": request.form.get("requestDescription"),
                "informationDataFormat": request.form.get("informationDataFormat"),
            }
        ],
    }


def build_containment_dict(nq_id, *, default_action_party, reference_file=None):
    """Build a ContainmentAction dict matching the AAS ContainmentAction submodel.

    `reference_file` is an attachment dict already saved by the caller (see
    `save_upload`) or None — the ActionReference.referenceFile element is a
    single xs:anyURI, so only one uploaded file is carried.
    """
    return {
        "nonQualityId": nq_id,
        "actionId": generate_random_id(length=8),
        "actionParty": request.form.get("actionParty", default_action_party),
        "title": request.form.get("title"),
        "description": request.form.get("description"),
        "responsible": request.form.get("responsible"),
        "plannedImplementationDate": request.form.get("plannedImplementationDate"),
        "actualImplementationDate": request.form.get("actualImplementationDate"),
        "status": request.form.get("status", "Open"),
        "ActionReference": [
            {
                "referenceType": request.form.get("referenceType"),
                "referenceNumber": request.form.get("referenceNumber"),
                "referenceFile": reference_file or "",
            }
        ],
    }
