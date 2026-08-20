# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

"""Jinja template filters (registered globally in app.py).
"""


def format_value(value):
    """Format a value for display: booleans as Yes/No, None as 'Not specified'."""

    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str) and value.lower() in ["true", "false"]:
        return "Yes" if value.lower() == "true" else "No"
    return str(value) if value is not None else "Not specified"


_DIFF_FIELDS = [
    (
        "proposedCompletionFrom",
        "Proposed Completion From",
        lambda d: (d.get("ProposedCompletionPeriod") or {}).get(
            "proposedCompletionFrom"
        ),
    ),
    (
        "proposedCompletionTo",
        "Proposed Completion To",
        lambda d: (d.get("ProposedCompletionPeriod") or {}).get("proposedCompletionTo"),
    ),
    ("dispositionType", "Disposition Type", lambda d: d.get("dispositionType")),
    ("decisionReason", "Decision Reason", lambda d: d.get("decisionReason")),
]


def get_disposition_comparisons(disposition_list):
    """One entry per disposition, each carrying a side-by-side (git-style)
    comparison of just the Proposed Completion Details / Disposition Proposal
    fields against the previous disposition (no comparison for the first)."""

    if not disposition_list:
        return []
    results = []
    prev = None
    for disposition in disposition_list:
        fields = {}
        for key, label, getter in _DIFF_FIELDS:
            new_val = getter(disposition)
            old_val = getter(prev) if prev is not None else None
            fields[key] = {
                "label": label,
                "old": old_val,
                "new": new_val,
                "changed": prev is not None and old_val != new_val,
            }
        results.append(
            {"disposition": disposition, "is_first": prev is None, "fields": fields}
        )
        prev = disposition
    return results
