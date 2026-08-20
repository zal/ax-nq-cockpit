# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Single-role SQLite store.

One database per container. Three small tables:

  nq            — the NQ records, stored as one JSON blob each (AAS-aligned dict)
  notifications — the inbox (one row per inbound event from the partner)
  offers        — the mock dataspace "provider" store: payloads we have published
                  for the partner to pull (the real EDC keeps these in the connector).
"""

import json
import os
import sqlite3
from datetime import datetime

import config


def _now():
    return datetime.now().astimezone().isoformat()


def _conn():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(c):
    cols = {
        row[1] for row in c.execute("PRAGMA table_info(trusted_partners)").fetchall()
    }
    if "partner_did" in cols:
        c.execute("DROP TABLE trusted_partners")


def init_db():
    with _conn() as c:
        _migrate(c)
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS nq (
                id          TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nq_id       TEXT,
                kind        TEXT,
                message     TEXT,
                is_read     INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS offers (
                asset_id     TEXT PRIMARY KEY,
                nq_id        TEXT,
                allowed_party TEXT,
                payload      TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agreements (
                asset_id     TEXT NOT NULL,
                party        TEXT NOT NULL,
                agreement_id TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                PRIMARY KEY (asset_id, party)
            );
            CREATE TABLE IF NOT EXISTS connector_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS trusted_partners (
                edc_connector_did TEXT PRIMARY KEY,
                edc_hostname      TEXT,
                keycloak_url      TEXT,
                label             TEXT
            );
            """
        )


# --- NQ records ------------------------------------------------------------
def save_nq(nq_id, data):
    now = _now()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO nq (id, data, created_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
            """,
            (nq_id, json.dumps(data), now, now),
        )


def get_nq(nq_id):
    with _conn() as c:
        row = c.execute("SELECT data FROM nq WHERE id = ?", (nq_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def all_nqs():
    with _conn() as c:
        rows = c.execute("SELECT id, data FROM nq ORDER BY updated_at DESC").fetchall()
    return [(r["id"], json.loads(r["data"])) for r in rows]


def all_nqs_dict():
    return dict(all_nqs())


def local_nqs_dict():
    return {nq_id: data for nq_id, data in all_nqs() if not data.get("_received")}


def received_nqs_dict():
    return {nq_id: data for nq_id, data in all_nqs() if data.get("_received")}


def delete_nq(nq_id):
    with _conn() as c:
        c.execute("DELETE FROM nq WHERE id = ?", (nq_id,))


# --- notifications (inbox) -------------------------------------------------
def add_notification(nq_id, kind, message):
    with _conn() as c:
        c.execute(
            "INSERT INTO notifications (nq_id, kind, message, created_at) VALUES (?, ?, ?, ?)",
            (nq_id, kind, message, _now()),
        )


def notifications_dict():
    """Return {nq_id: {kind, message, created_at}} (most recent per NQ)."""
    out = {}
    with _conn() as c:
        rows = c.execute(
            "SELECT nq_id, kind, message, created_at FROM notifications ORDER BY created_at ASC"
        ).fetchall()
    for r in rows:
        out[r["nq_id"]] = {
            "kind": r["kind"],
            "message": r["message"],
            "created_at": r["created_at"],
        }
    return out


def get_notification(nq_id):
    """Most recent notification for a single NQ, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT kind, message, created_at FROM notifications WHERE nq_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (nq_id,),
        ).fetchone()
    return (
        {
            "kind": row["kind"],
            "message": row["message"],
            "created_at": row["created_at"],
        }
        if row
        else None
    )


def delete_notifications_for(nq_id):
    with _conn() as c:
        c.execute("DELETE FROM notifications WHERE nq_id = ?", (nq_id,))


# --- mock dataspace offer store -------------------------------------------
def save_offer(asset_id, nq_id, allowed_party, payload):
    with _conn() as c:
        c.execute(
            """
            INSERT INTO offers (asset_id, nq_id, allowed_party, payload, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                payload=excluded.payload, allowed_party=excluded.allowed_party,
                updated_at=excluded.updated_at
            """,
            (asset_id, nq_id, allowed_party, json.dumps(payload), _now()),
        )


def get_offer(asset_id):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM offers WHERE asset_id = ?", (asset_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "asset_id": row["asset_id"],
        "nq_id": row["nq_id"],
        "allowed_party": row["allowed_party"],
        "payload": json.loads(row["payload"]),
    }


def list_offer_ids_for(party):
    """Asset ids the given party is allowed to pull (mock catalog)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT asset_id FROM offers WHERE allowed_party = ?", (party,)
        ).fetchall()
    return [r["asset_id"] for r in rows]


# --- consumer-side contract agreements (For contract reuse) -------------------------------------
def get_agreement(asset_id, party):
    with _conn() as c:
        row = c.execute(
            "SELECT agreement_id FROM agreements WHERE asset_id = ? AND party = ?",
            (asset_id, party),
        ).fetchone()
    return row["agreement_id"] if row else None


def save_agreement(asset_id, party, agreement_id):
    with _conn() as c:
        c.execute(
            """
            INSERT INTO agreements (asset_id, party, agreement_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(asset_id, party) DO NOTHING
            """,
            (asset_id, party, agreement_id, _now()),
        )


# --- connector settings -------------------------------------------------------
_CONNECTOR_KEYS = (
    "connector_hostname",
    "identity_hostname",
    "x_api_key",
    "legal_entity_id",
)


def get_transport_mode():
    with _conn() as c:
        row = c.execute(
            "SELECT value FROM connector_settings WHERE key='transport_mode'"
        ).fetchone()
    return row["value"] if row else "mock"


def save_transport_mode(mode):
    with _conn() as c:
        c.execute(
            "INSERT INTO connector_settings (key, value) VALUES ('transport_mode', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (mode,),
        )


def get_connector_settings():
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM connector_settings").fetchall()
    result = {k: "" for k in _CONNECTOR_KEYS}
    for r in rows:
        if r["key"] in result:
            result[r["key"]] = r["value"]
    return result


def save_connector_settings(
    connector_hostname, identity_hostname, x_api_key, legal_entity_id
):
    values = {
        "connector_hostname": connector_hostname or "",
        "identity_hostname": identity_hostname or "",
        "x_api_key": x_api_key or "",
        "legal_entity_id": legal_entity_id or "",
    }
    with _conn() as c:
        for key, value in values.items():
            c.execute(
                "INSERT INTO connector_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


# --- trusted partners ---------------------------------------------------------
_PARTNER_COLS = (
    "edc_connector_did",
    "edc_hostname",
    "keycloak_url",
    "label",
)


def get_trusted_partners():
    with _conn() as c:
        rows = c.execute(
            f"SELECT {', '.join(_PARTNER_COLS)} FROM trusted_partners"
        ).fetchall()
    return [dict(zip(_PARTNER_COLS, r)) for r in rows]


def upsert_trusted_partner(
    edc_connector_did, edc_hostname=None, keycloak_url=None, label=None
):
    with _conn() as c:
        c.execute(
            """
            INSERT INTO trusted_partners
                (edc_connector_did, edc_hostname, keycloak_url, label)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(edc_connector_did) DO UPDATE SET
                edc_hostname=excluded.edc_hostname,
                keycloak_url=excluded.keycloak_url,
                label=excluded.label
            """,
            (edc_connector_did, edc_hostname, keycloak_url, label),
        )


def remove_trusted_partner(edc_connector_did):
    with _conn() as c:
        c.execute(
            "DELETE FROM trusted_partners WHERE edc_connector_did = ?",
            (edc_connector_did,),
        )
