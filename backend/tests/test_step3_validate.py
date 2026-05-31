"""Unit tests for step3_implied_generator._validate_and_normalise."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pipeline.step3_implied_generator import _validate_and_normalise, _parse_llm_response

STEP1 = [
    {"req_id": "REQ-001", "description": "System must allow users to log in", "functional_area": "auth"},
    {"req_id": "REQ-002", "description": "System must display a task list", "functional_area": "tasks"},
]
STEP2 = [
    {"req_id": "OBV-001", "description": "System must provide a way to navigate to the task list", "functional_area": "navigation"},
]


def test_l1a_placement_and_depends_on_filter():
    items = [
        {
            "description": "System must display a profile screen.",
            "reasoning": "Pattern A -- login stated; no profile screen found",
            "confidence_score": 0.88,
            "confidence_reason": "Auth pattern fires",
            "category": "sop",
            "depends_on": ["REQ-001", "REQ-999"],  # REQ-999 invalid
            "priority": "high",
            "functional_area": "auth",
            "path": [{"type": "node", "label": "Profile", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert len(valid) == 1, f"Expected 1 valid, got {len(valid)}"
    assert dropped == 0
    r = valid[0]
    assert r["req_id"] == "GEN-001"
    assert r["placement"] == "l1a"
    assert r["strength"] is None
    assert r["weight"] == 3.0  # high priority
    assert r["depends_on"] == ["REQ-001"]  # REQ-999 filtered out
    assert r["tag"] == "generated"
    assert r["source"] == "generated"


def test_l1b_strongly_implied():
    items = [
        {
            "description": "System must allow filtering tasks.",
            "reasoning": "SOP-B -- task list is a list node",
            "confidence_score": 0.65,
            "confidence_reason": "List node; filter expected",
            "category": "sop",
            "depends_on": ["REQ-002", "OBV-001"],
            "functional_area": "tasks",
            "path": [{"type": "node", "label": "Task List", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert len(valid) == 1
    r = valid[0]
    assert r["placement"] == "l1b"
    assert r["strength"] == "strongly_implied"
    assert r["weight"] == 3.0
    assert "priority" not in r


def test_l1b_medium():
    items = [
        {
            "description": "System must provide data export.",
            "reasoning": "INF-D -- export not covered",
            "confidence_score": 0.50,
            "confidence_reason": "Moderately likely",
            "category": "inf",
            "depends_on": [],
            "path": [{"type": "node", "label": "Export", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert valid[0]["strength"] == "medium"
    assert valid[0]["weight"] == 2.0


def test_l1b_weak():
    items = [
        {
            "description": "System must provide bulk delete.",
            "reasoning": "INF-E -- power user feature",
            "confidence_score": 0.30,
            "confidence_reason": "Speculative",
            "category": "inf",
            "depends_on": [],
            "path": [{"type": "node", "label": "Bulk Delete", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert valid[0]["strength"] == "weak"
    assert valid[0]["weight"] == 1.0


def test_duplicate_of_stated_dropped():
    items = [
        {
            "description": "System must allow users to log in",  # exact match in STEP1
            "reasoning": "dup",
            "confidence_score": 0.9,
            "confidence_reason": "dup",
            "category": "sop",
            "depends_on": [],
            "path": [{"type": "node", "label": "Login", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert len(valid) == 0
    assert dropped == 1


def test_duplicate_of_obvious_dropped():
    items = [
        {
            "description": "System must provide a way to navigate to the task list",  # exact match in STEP2
            "reasoning": "dup",
            "confidence_score": 0.9,
            "confidence_reason": "dup",
            "category": "sop",
            "depends_on": [],
            "path": [{"type": "node", "label": "Task List", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert len(valid) == 0
    assert dropped == 1


def test_invalid_confidence_dropped():
    items = [
        {
            "description": "System must do something.",
            "reasoning": "test",
            "confidence_score": None,
            "confidence_reason": "N/A",
            "category": "sop",
            "depends_on": [],
            "path": [{"type": "node", "label": "Something", "primary": True}],
        },
        {
            "description": "System must do another thing.",
            "reasoning": "test",
            "confidence_score": 1.5,  # out of range
            "confidence_reason": "N/A",
            "category": "sop",
            "depends_on": [],
            "path": [{"type": "node", "label": "Another Thing", "primary": True}],
        },
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert len(valid) == 0
    assert dropped == 2


def test_invalid_category_dropped():
    items = [
        {
            "description": "System must do something.",
            "reasoning": "test",
            "confidence_score": 0.75,
            "confidence_reason": "N/A",
            "category": "made_up_category",
            "depends_on": [],
            "path": [{"type": "node", "label": "Something", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert len(valid) == 0
    assert dropped == 1


def test_missing_reasoning_dropped():
    items = [
        {
            "description": "System must do something.",
            "reasoning": "",
            "confidence_score": 0.75,
            "confidence_reason": "N/A",
            "category": "sop",
            "depends_on": [],
            "path": [{"type": "node", "label": "Something", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert len(valid) == 0
    assert dropped == 1


def test_req_id_renumbering():
    items = [
        {
            "description": "System must show profile.",
            "reasoning": "Pattern A",
            "confidence_score": 0.85,
            "confidence_reason": "Auth",
            "category": "sop",
            "depends_on": [],
            "priority": "high",
            "path": [{"type": "node", "label": "Profile", "primary": True}],
        },
        {
            "description": "System must show sync status.",
            "reasoning": "Pattern D",
            "confidence_score": 0.70,
            "confidence_reason": "Sync stated",
            "category": "sop",
            "depends_on": [],
            "path": [{"type": "node", "label": "Sync Status", "primary": True}],
        },
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    assert valid[0]["req_id"] == "GEN-001"
    assert valid[1]["req_id"] == "GEN-002"


def test_parse_llm_response_with_preamble():
    raw = """
Here is my YES/NO reasoning:
- Node A: YES
- Node B: NO

[{"req_id": "GEN-001", "description": "System must display profile.", "reasoning": "test", "confidence_score": 0.85, "confidence_reason": "ok", "category": "sop_a", "depends_on": [], "priority": "high", "tag": "generated", "source": "generated", "weight": 3.0, "testable": true, "functional_area": "auth", "l1_recommendation": "l1a", "strength": null}]
"""
    result = _parse_llm_response(raw)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["req_id"] == "GEN-001"


def test_sop_b_count_vs_inf_count():
    _p = lambda label: [{"type": "node", "label": label, "primary": True}]
    items = [
        {"description": "System must filter.", "reasoning": "sop test", "confidence_score": 0.82, "confidence_reason": "ok", "category": "sop", "depends_on": [], "priority": "medium", "path": _p("Filter")},
        {"description": "System must search.", "reasoning": "sop test", "confidence_score": 0.81, "confidence_reason": "ok", "category": "sop", "depends_on": [], "priority": "medium", "path": _p("Search")},
        {"description": "System must show audit log.", "reasoning": "inf test", "confidence_score": 0.50, "confidence_reason": "ok", "category": "inf", "depends_on": [], "path": _p("Audit Log")},
        {"description": "System must export CSV.", "reasoning": "inf test", "confidence_score": 0.45, "confidence_reason": "ok", "category": "inf", "depends_on": [], "path": _p("Export")},
        {"description": "System must cross-link.", "reasoning": "inf test", "confidence_score": 0.60, "confidence_reason": "ok", "category": "inf", "depends_on": [], "path": _p("Cross Link")},
    ]
    valid, dropped = _validate_and_normalise(items, STEP1, STEP2)
    sop = sum(1 for r in valid if r.get("category") == "sop")
    inf = sum(1 for r in valid if r.get("category") == "inf")
    assert sop == 2
    assert inf == 3


if __name__ == "__main__":
    test_l1a_placement_and_depends_on_filter()
    test_l1b_strongly_implied()
    test_l1b_medium()
    test_l1b_weak()
    test_duplicate_of_stated_dropped()
    test_duplicate_of_obvious_dropped()
    test_invalid_confidence_dropped()
    test_invalid_category_dropped()
    test_missing_reasoning_dropped()
    test_req_id_renumbering()
    test_parse_llm_response_with_preamble()
    test_sop_b_count_vs_inf_count()
    print("All tests passed")
