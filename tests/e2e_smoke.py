# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0
"""End-to-end smoke test: boots a customer and a supplier instance and drives
the full mock-dataspace NQ workflow over HTTP.

    docker build -t nq-cockpit -f docker/Dockerfile .
    docker run --rm nq-cockpit python tests/e2e_smoke.py

Uses fresh temporary databases, dev auto-login (no Keycloak), and no BaSyx
(reads fall back to SQLite), so it needs no Keycloak/BaSyx containers running.
Exit code 0 = every checkpoint passed.
"""
import os
import re
import subprocess
import sys
import tempfile
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUST = "http://localhost:5001"
SUPP = "http://localhost:5002"

procs = []
tmpdir = tempfile.mkdtemp(prefix="nq-e2e-")
passed = 0


def start(role, port, partner):
    env = os.environ.copy()
    # Force dev auto-login and the SQLite fallback regardless of the caller's shell.
    for var in ("OIDC_ISSUER", "OIDC_INTERNAL_ISSUER", "BASYX_ENV_URL"):
        env.pop(var, None)
    env.update({
        "ROLE": role, "PORT": str(port),
        "PARTNER_URL": partner,
        "DATA_DIR": os.path.join(tmpdir, role),
    })
    log = open(os.path.join(tmpdir, f"{role}.log"), "w")
    procs.append(subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env,
                                  stdout=log, stderr=subprocess.STDOUT))


def dump_logs():
    for role in ("customer", "supplier"):
        path = os.path.join(tmpdir, f"{role}.log")
        if os.path.exists(path):
            with open(path) as f:
                tail = f.readlines()[-15:]
            print(f"\n--- {role}.log (tail) ---\n" + "".join(tail), file=sys.stderr)


def wait_up(base):
    for _ in range(40):
        try:
            requests.get(base + "/login", timeout=2)
            return
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    dump_logs()
    raise SystemExit(f"FAIL: {base} did not come up")


def check(cond, label):
    global passed
    print(f"[{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        dump_logs()
        raise SystemExit(1)
    passed += 1


try:
    start("customer", 5001, SUPP)
    start("supplier", 5002, CUST)
    wait_up(CUST)
    wait_up(SUPP)

    c = requests.Session()
    s = requests.Session()
    c.get(CUST + "/login")   # dev auto-login
    s.get(SUPP + "/login")

    # 1. customer creates + shares an NQ
    form = {
        "nonQualityTitle": "E2E scratch on bracket",
        "DigitalNameplate": "DN-1", "NonQualityQuantity": "2",
        "problemShortDescription": "Scratch", "problemLongDescription": "Deep scratch on surface",
        "issueGroup": "Surface", "issueCode": "SC-01",
        "stepOfProduction": "Assembly", "detectedHow": "Visual", "detectedWhen": "2026-07-17T09:00",
        "detectedWhere": "Line 2", "detectedByWhom": "QA",
        "affectedPurchaseOrderNumber": "PO-123", "purchaseOrderPositionNumber": "10",
        "customerACAGECode": "C123", "customerGroupName": "Grp", "customerOrganizationName": "Org",
        "customerPlantCode": "PL1", "customerPlantName": "Plant One", "supplierACAGECode": "S456",
        "customerPartNumber": "BLD-ACTB-0002", "traceabilityType": "SERIAL", "traceabilityNumber": "SN-1",
    }
    r = c.post(CUST + "/customer/customer_form", data=form)
    check(r.status_code == 200, f"customer creates+shares NQ ({r.status_code})")
    ids = re.findall(r"/customer/nq/([A-Za-z0-9]+)", r.text)
    check(ids, "nq_id visible on customer home")
    nq_id = ids[0]
    print("    nq_id =", nq_id)

    # 2. supplier inbox shows the notification; supplier fetches the NQ
    r = s.get(SUPP + "/supplier/")
    check(r.status_code == 200 and nq_id in r.text, "supplier inbox shows notification")
    r = s.post(SUPP + f"/supplier/fetch_nq/{nq_id}", allow_redirects=True)
    check(r.status_code == 200, f"supplier fetches NQ ({r.status_code})")

    # 3. supplier detail view renders with the supplier-only blocks
    r = s.get(SUPP + f"/supplier/nq/{nq_id}")
    check(r.status_code == 200, "supplier NQ detail renders")
    check("read-only view" in r.text, "supplier sees read-only note")
    check("Edit Non-Quality Report" not in r.text, "supplier has no Edit button")
    check("Close Non-Quality" not in r.text, "supplier has no Close button")

    # 4. supplier submits a disposition
    disp = {
        "contactPersonName": "Sam Supplier", "dispositionType": "AcceptAsIs",
        "decisionReason": "Within tolerance",
    }
    r = s.post(SUPP + f"/supplier/nq/{nq_id}/submit_disposition", data=disp, allow_redirects=True)
    check(r.status_code == 200, f"supplier submits disposition ({r.status_code})")

    # 5. customer sees the pending update, fetches it, disposition visible
    r = c.get(CUST + f"/customer/nq/{nq_id}")
    check(r.status_code == 200 and "Fetch update" in r.text, "customer sees pending update banner")
    r = c.post(CUST + f"/customer/nq/{nq_id}/fetch_update", allow_redirects=True)
    check(r.status_code == 200, f"customer fetches update ({r.status_code})")
    r = c.get(CUST + f"/customer/nq/{nq_id}")
    check("Within tolerance" in r.text, "customer sees supplier disposition")
    check("Accept" in r.text, "customer sees respond buttons")

    # 6. customer accepts the disposition
    r = c.post(CUST + f"/customer/nq/{nq_id}/disposition/0/respond",
               data={"decision": "accepted"}, allow_redirects=True)
    check(r.status_code == 200, f"customer accepts disposition ({r.status_code})")

    # 7. customer creates a containment action
    cont = {
        "actionParty": "Customer", "title": "Quarantine parts",
        "description": "Move affected parts to quarantine", "responsible": "QA Lead",
        "plannedImplementationDate": "2026-07-20", "status": "Open",
    }
    r = c.post(CUST + f"/customer/nq/{nq_id}/create_containment", data=cont, allow_redirects=True)
    check(r.status_code == 200, f"customer creates containment action ({r.status_code})")
    r = c.get(CUST + f"/customer/nq/{nq_id}")
    check("Quarantine parts" in r.text, "containment action listed on customer side")
    m = re.search(rf"/customer/nq/{nq_id}/containment/([A-Za-z0-9-]+)", r.text)
    check(m, "containment detail link present")
    r = c.get(CUST + f"/customer/nq/{nq_id}/containment/{m.group(1)}")
    check(r.status_code == 200, "containment detail view renders (customer)")

    # 8. supplier pulls the containment update and sees it
    r = s.post(SUPP + f"/supplier/fetch_nq/{nq_id}", allow_redirects=True)
    check(r.status_code == 200, "supplier pulls update")
    r = s.get(SUPP + f"/supplier/nq/{nq_id}")
    check("Quarantine parts" in r.text, "containment action visible on supplier side")

    # 9. customer closes the NQ
    r = c.post(CUST + f"/customer/nq/close/{nq_id}", allow_redirects=True)
    check(r.status_code == 200, f"customer closes NQ ({r.status_code})")
    r = c.get(CUST + f"/customer/nq/{nq_id}")
    check("CLOSED" in r.text, "NQ shows CLOSED on customer side")

    # 10. every remaining GET page on both sides renders
    for base, sess, paths in (
        (CUST, c, ["/", "/customer/customer_home", "/customer/customer_form", "/edc/cockpit",
                   f"/customer/nq/{nq_id}/edit"]),
        (SUPP, s, ["/", "/supplier/", "/edc/cockpit"]),
    ):
        for path in paths:
            r = sess.get(base + path, allow_redirects=True)
            check(r.status_code == 200, f"GET {base}{path} -> {r.status_code}")

    print(f"\nE2E SMOKE TEST PASSED ({passed} checks)")
finally:
    for p in procs:
        p.terminate()
