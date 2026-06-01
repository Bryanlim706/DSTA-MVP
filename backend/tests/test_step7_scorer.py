import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.step7_scorer import _compute_score, run


# ---------------------------------------------------------------------------
# _compute_score
# ---------------------------------------------------------------------------

def test_compute_score_perfect():
    reqs = [
        {"req_id": "REQ-001", "weight": 2.0},
        {"req_id": "REQ-002", "weight": 3.0},
    ]
    e_lookup = {"REQ-001": 1.0, "REQ-002": 1.0}
    score, detail = _compute_score(reqs, e_lookup)
    assert score == 1.0
    assert detail["requirement_count"] == 2
    assert detail["denominator"] == 5.0
    assert detail["numerator"] == 5.0


def test_compute_score_zero():
    reqs = [{"req_id": "REQ-001", "weight": 2.0}]
    e_lookup = {"REQ-001": 0.0}
    score, detail = _compute_score(reqs, e_lookup)
    assert score == 0.0
    assert detail["numerator"] == 0.0


def test_compute_score_weighted_average():
    # REQ-001: e=1.0, w=1.0 → contributes 1.0
    # REQ-002: e=0.0, w=3.0 → contributes 0.0
    # total = 1.0 / 4.0 = 0.25
    reqs = [
        {"req_id": "REQ-001", "weight": 1.0},
        {"req_id": "REQ-002", "weight": 3.0},
    ]
    e_lookup = {"REQ-001": 1.0, "REQ-002": 0.0}
    score, detail = _compute_score(reqs, e_lookup)
    assert abs(score - 0.25) < 1e-9
    assert detail["numerator"] == 1.0
    assert detail["denominator"] == 4.0


def test_compute_score_missing_req_in_lookup_defaults_zero():
    reqs = [{"req_id": "REQ-001", "weight": 2.0}]
    e_lookup = {}  # REQ-001 not in step6 mapped
    score, _ = _compute_score(reqs, e_lookup)
    assert score == 0.0


def test_compute_score_empty_reqs():
    score, detail = _compute_score([], {})
    assert score == 0.0
    assert detail["requirement_count"] == 0
    assert detail["denominator"] == 0.0


def test_compute_score_partial():
    # e=0.5 for both, equal weights
    reqs = [{"req_id": "R1", "weight": 2.0}, {"req_id": "R2", "weight": 2.0}]
    e_lookup = {"R1": 0.5, "R2": 0.5}
    score, _ = _compute_score(reqs, e_lookup)
    assert score == 0.5


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _make_step6(mapped):
    return {"mapped": mapped, "unlinked_l2": [], "unlinked_l3": [], "error": None}


def _make_step3_5(l1a, l1b=None):
    return {
        "confirmed_requirements": l1a,
        "advisory_requirements": l1b or [],
    }


def test_run_basic_fcom():
    step6 = _make_step6([
        {"req_id": "REQ-001", "e_score": 1.0},
        {"req_id": "REQ-002", "e_score": 0.5},
    ])
    step3_5 = _make_step3_5([
        {"req_id": "REQ-001", "description": "Login", "weight": 2.0},
        {"req_id": "REQ-002", "description": "View dashboard", "weight": 2.0},
    ])
    result = run(step6, step3_5)
    assert result["error"] is None
    assert result["fcom"] == 0.75
    assert result["fa"] == 0.0  # no l1b


def test_run_fa_uses_advisory():
    step6 = _make_step6([
        {"req_id": "GEN-001", "e_score": 1.0},
        {"req_id": "GEN-002", "e_score": 0.0},
    ])
    step3_5 = _make_step3_5(
        l1a=[],
        l1b=[
            {"req_id": "GEN-001", "description": "Filter tasks", "weight": 3.0, "strength": "strongly_implied"},
            {"req_id": "GEN-002", "description": "Export data", "weight": 1.0, "strength": "weak"},
        ],
    )
    result = run(step6, step3_5)
    # FA = (1.0*3.0 + 0.0*1.0) / 4.0 = 0.75
    assert abs(result["fa"] - 0.75) < 1e-4


def test_run_missing_l1a_advisory():
    step6 = _make_step6([
        {"req_id": "REQ-001", "e_score": 0.0},
        {"req_id": "REQ-002", "e_score": 1.0},
    ])
    step3_5 = _make_step3_5([
        {"req_id": "REQ-001", "description": "Missing feature", "weight": 2.0},
        {"req_id": "REQ-002", "description": "Present feature", "weight": 2.0},
    ])
    result = run(step6, step3_5)
    assert len(result["fcom_advisory"]["missing_l1a"]) == 1
    assert result["fcom_advisory"]["missing_l1a"][0]["req_id"] == "REQ-001"


def test_run_missing_l1b_advisory():
    step6 = _make_step6([
        {"req_id": "GEN-001", "e_score": 0.3},
    ])
    step3_5 = _make_step3_5(
        l1a=[],
        l1b=[{"req_id": "GEN-001", "description": "Bulk delete", "weight": 1.0, "strength": "weak"}],
    )
    result = run(step6, step3_5)
    assert len(result["fa_advisory"]["missing_l1b"]) == 1
    assert result["fa_advisory"]["missing_l1b"][0]["req_id"] == "GEN-001"


def test_run_missing_l1a_threshold_at_0_5():
    # e=0.5 should NOT appear in missing_l1a (threshold is < 0.5)
    step6 = _make_step6([{"req_id": "REQ-001", "e_score": 0.5}])
    step3_5 = _make_step3_5([{"req_id": "REQ-001", "description": "Edge case", "weight": 2.0}])
    result = run(step6, step3_5)
    assert result["fcom_advisory"]["missing_l1a"] == []


def test_run_unlinked_passthrough():
    step6 = {
        "mapped": [],
        "unlinked_l2": [{"route": "/admin", "title": "Admin", "note": "..."}],
        "unlinked_l3": [{"method": "DELETE", "path": "/api/x", "handler": "h", "file": "f", "note": "..."}],
        "error": None,
    }
    step3_5 = _make_step3_5([])
    result = run(step6, step3_5)
    assert len(result["fcom_advisory"]["unlinked_routes"]) == 1
    assert len(result["fcom_advisory"]["unlinked_endpoints"]) == 1


def test_run_empty_everything():
    result = run({"mapped": [], "unlinked_l2": [], "unlinked_l3": []}, {"confirmed_requirements": [], "advisory_requirements": []})
    assert result["fcom"] == 0.0
    assert result["fa"] == 0.0
    assert result["error"] is None


def test_run_missing_l1a_sorted_by_e_score():
    step6 = _make_step6([
        {"req_id": "REQ-001", "e_score": 0.4},
        {"req_id": "REQ-002", "e_score": 0.0},
        {"req_id": "REQ-003", "e_score": 0.2},
    ])
    step3_5 = _make_step3_5([
        {"req_id": "REQ-001", "description": "A", "weight": 1.0},
        {"req_id": "REQ-002", "description": "B", "weight": 1.0},
        {"req_id": "REQ-003", "description": "C", "weight": 1.0},
    ])
    result = run(step6, step3_5)
    ids = [r["req_id"] for r in result["fcom_advisory"]["missing_l1a"]]
    assert ids == ["REQ-002", "REQ-003", "REQ-001"]


def test_run_detail_fields():
    step6 = _make_step6([{"req_id": "REQ-001", "e_score": 0.8}])
    step3_5 = _make_step3_5([{"req_id": "REQ-001", "description": "X", "weight": 5.0}])
    result = run(step6, step3_5)
    assert result["fcom_detail"]["numerator"] == round(0.8 * 5.0, 4)
    assert result["fcom_detail"]["denominator"] == 5.0
    assert result["fcom_detail"]["requirement_count"] == 1
