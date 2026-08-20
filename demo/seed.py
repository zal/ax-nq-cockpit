# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Fixed demo NQs for the customer portal.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db import db

_CUSTOMER_SITE = {
    "customerACAGECode": "AX_0046",
    "customerGroupName": "Aerospace-X GmbH",
    "customerOrganizationName": "Aerospace-X Operations GmbH",
    "customerPlantCode": "PLT-023",
    "customerPlantName": "Highrise Hub",
}
_SUPPLIER_ACAGE = "AX_0187"


def _nq(
    nq_id,
    title,
    created,
    part_no,
    part_name,
    part_class,
    nameplate,
    trace_no,
    qty,
    short_desc,
    long_desc,
    issue_group,
    issue_code,
    safety,
    step,
    msn,
    version,
    ata,
    how,
    where,
    by_whom,
    po_no,
    po_pos,
    airline,
    final_customer,
    commodity,
    sub_commodity,
    program,
    status="OPEN",
):
    return {
        "NonQualityHeader": {
            "nonQualityId": nq_id,
            "nonQualityTitle": title,
            "nonQualityStatus": status,
            "nonQualityCreationDate": created,
            "nonQualityLastUpdateDate": created,
            "customerComment": "Demo record — seeded at startup.",
        },
        "NonQualityDescription": {
            "problemShortDescription": short_desc,
            "problemLongDescription": long_desc,
            "issueGroup": issue_group,
            "issueCode": issue_code,
            "defectImage": [],
            "defectDocument": [],
            "safetyRelated": safety,
            "subPartAffectedComponent": [],
        },
        "NonQualityDiscovery": {
            "stepOfProduction": step,
            "msn": msn,
            "versionOfAircraft": version,
            "ataSection": ata,
            "detectedHow": how,
            "detectedWhen": created,
            "detectedWhere": where,
            "detectedByWhom": by_whom,
        },
        "ProductScope": {
            "airlineCustomer": airline,
            "finalCustomer": final_customer,
            "commodity": commodity,
            "subCommodity": sub_commodity,
            "program": program,
        },
        "PartIdentification": [
            {
                "partDigitalNameplate": nameplate,
                "affectedQuantity": str(qty),
                "traceabilityType": "Serial Number",
                "traceabilityNumber": trace_no,
                "partClass": part_class,
                "customerPartNumber": part_no,
                "customerPartName": part_name,
            }
        ],
        "ImpactedPurchaseOrder": {
            "affectedPurchaseOrderNumber": po_no,
            "purchaseOrderPositionNumber": po_pos,
        },
        "CollaborationPartners": {
            "CustomerSite": dict(_CUSTOMER_SITE),
            "SupplierSite": {"supplierACAGECode": _SUPPLIER_ACAGE},
        },
        "Disposition": [],
        "ContainmentActions": [],
    }


DEMO_NQS = [
    _nq(
        "demoNQ01",
        "Cracked engine mount bracket",
        "2026-07-01T09:15:00",
        "MNT-ENGB-0311",
        "Engine Mount Bracket",
        "Structural Engine Component",
        "https://digitalnameplate.example.com/engine/mount-bracket/M41-2026-EM11P7Q1",
        "S/N-14062026-3011",
        1,
        "Crack at the forward mounting lug of the engine mount bracket",
        "During final engine build a 6 mm crack was found propagating from the forward "
        "mounting lug bolt hole. The crack is on a primary load path and grounds the "
        "assembly until dispositioned by the supplier.",
        "Material Non-Conformance",
        "MNC-018-CRK",
        True,
        "Final assembly",
        "2210",
        "A320",
        "ATA-71",
        "Visual inspection",
        "Highrise Hub",
        "QA Team",
        "AEPA-0041",
        "1",
        "Christiana Airways",
        "Skybound Aircraft Corporation",
        "Engine",
        "Pylon",
        "SA Series",
        "CLOSED",
    ),
    _nq(
        "demoNQ02",
        "Hydraulic actuator seal leak",
        "2026-07-05T13:40:00",
        "ACT-HYDR-0205",
        "Hydraulic Actuator",
        "Hydraulic Component",
        "https://digitalnameplate.example.com/hydraulics/actuator/H27-2026-HA05R3S9",
        "S/N-20062026-2050",
        2,
        "External fluid leak at the rod-end seal during pressure test",
        "The landing-gear actuator failed the acceptance pressure test with visible "
        "hydraulic fluid weeping past the rod-end seal at 200 bar. The unit does not "
        "hold pressure and must be returned to the supplier for seal investigation.",
        "Functional Non-Conformance",
        "FNC-026-LEK",
        True,
        "Functional test",
        "2214",
        "A320",
        "ATA-29",
        "Pressure test",
        "Highrise Hub",
        "Test Bench Team",
        "AEPA-0044",
        "3",
        "Christiana Airways",
        "Skybound Aircraft Corporation",
        "Systems",
        "Hydraulics",
        "SA Series",
    ),
    _nq(
        "demoNQ03",
        "Corroded fuselage skin panel",
        "2026-07-08T08:05:00",
        "PNL-SKIN-0450",
        "Fuselage Skin Panel",
        "Primary Structure",
        "https://digitalnameplate.example.com/fuselage/skin-panel/S53-2026-SP45T4U5",
        "S/N-28062026-4501",
        4,
        "Surface corrosion across the panel outer skin",
        "Incoming inspection found pitting corrosion spread over roughly 20% of the outer "
        "skin surface, indicating a breakdown of the surface protection during storage or "
        "transport. The panel cannot be accepted for a primary structural application.",
        "Surface Non-Conformance",
        "SNC-058-COR",
        False,
        "Incoming inspection",
        "2219",
        "A320",
        "ATA-53",
        "Visual inspection",
        "Highrise Hub",
        "Goods Receiving QA",
        "SPA-0130",
        "7",
        "Christiana Airways",
        "Skybound Aircraft Corporation",
        "Structures",
        "Fuselage",
        "SA Series",
    ),
]


def _received_copy(nq):
    """A supplier-side view of a demo NQ, as if pulled from the customer."""
    received = copy.deepcopy(nq)
    received["_received"] = True
    received["PartnerUpdatePending"] = False
    return received


def _records_for_role():
    if config.ROLE == "customer":
        return DEMO_NQS
    if config.ROLE == "supplier":
        return [_received_copy(DEMO_NQS[0])]
    return []


def seed_demo_nqs(overwrite=False):
    """Insert the fixed demo NQs for the current role. Idempotent by default."""
    for nq in _records_for_role():
        nq_id = nq["NonQualityHeader"]["nonQualityId"]
        if overwrite or db.get_nq(nq_id) is None:
            db.save_nq(nq_id, nq)


def main():
    records = _records_for_role()
    if not records:
        print(f"ROLE={config.ROLE}: nothing to seed.")
        return
    db.init_db()
    seed_demo_nqs(overwrite=True)
    for nq in records:
        h = nq["NonQualityHeader"]
        print(
            f"seeded {h['nonQualityId']} ({h['nonQualityTitle']}) [{h['nonQualityStatus']}]"
        )
    print("Done.")


if __name__ == "__main__":
    main()
