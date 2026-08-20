# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Pull-based dataspace transport interface.

  offer(...)   provider registers an asset the counterparty may pull
  notify(...)  provider tells the counterparty "an asset is available to pull"
  pull(...)    consumer pulls: catalog -> negotiate -> transfer -> fetch

The mode ("mock" | "edc") is stored in the DB and switched at runtime in the
EDC Management Cockpit UI; it defaults to "mock".
"""
from abc import ABC, abstractmethod


class Transport(ABC):
    name = "base"

    @abstractmethod
    def offer(
        self, asset_id, nq_id, bundle, allowed_party, on_progress=None, is_new=True
    ):
        """Publish `bundle` (an AAS envelope) under `asset_id` for `allowed_party`."""

    @abstractmethod
    def notify(self, partner_url, asset_id, nq_id, kind, message=""):
        """Notify the partner that `asset_id` is available to pull."""

    @abstractmethod
    def pull(self, partner_url, asset_id, on_progress=None):
        """Pull and return the AAS envelope for `asset_id` from `partner_url`."""


_INSTANCE = None


def reset_transport():
    """Clear the cached singleton so the next get_transport() re-reads the mode from the DB."""
    global _INSTANCE
    _INSTANCE = None


def _current_mode():
    """Read transport mode from the DB; fall back to "mock" if the DB is unavailable."""
    try:
        from db.db import get_transport_mode

        return get_transport_mode()
    except Exception:
        return "mock"


def get_transport():
    """Return the configured transport singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        if _current_mode() == "edc":
            from transport.edc import EdcTransport

            _INSTANCE = EdcTransport()
        else:
            from transport.mock import MockTransport

            _INSTANCE = MockTransport()
    return _INSTANCE
