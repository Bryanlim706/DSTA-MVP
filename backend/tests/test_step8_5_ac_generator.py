"""Tests for step8_5_ac_generator — deterministic classification, slots, acw math."""
import pytest

from pipeline.step8_5_ac_generator import (
    _ac_id,
    _ac_slots,
    _classify_data_verb,
    _classify_goal_kind,
    _compute_acws,
    _test_type,
)


# ---------------------------------------------------------------------------
# _classify_goal_kind — precedence: data > structural > navigation > presence
# ---------------------------------------------------------------------------

def _edge(label: str, **kwargs) -> dict:
    return {"type": "edge", "label": label, "primary": True, **kwargs}


def _node(label: str) -> dict:
    return {"type": "node", "label": label, "primary": True}


def test_classify_data_wins_over_structural():
    path = [_edge("submit and filter"), _edge("filter results")]
    assert _classify_goal_kind(path) == "data"


def test_classify_data_wins_over_navigation():
    path = [_edge("create task"), _edge("navigate to dashboard")]
    assert _classify_goal_kind(path) == "data"


def test_classify_structural_wins_over_navigation():
    path = [_edge("filter by status"), _edge("navigate to list")]
    assert _classify_goal_kind(path) == "structural"


def test_classify_navigation_when_no_data_or_structural():
    path = [_edge("navigate to dashboard"), _node("Dashboard")]
    assert _classify_goal_kind(path) == "navigation"


def test_classify_presence_when_no_edges():
    path = [_node("Login Page"), {"type": "element", "label": "email input", "primary": True}]
    assert _classify_goal_kind(path) == "presence"


def test_classify_presence_empty_path():
    assert _classify_goal_kind([]) == "presence"


def test_classify_data_create():
    path = [_edge("add task")]
    assert _classify_goal_kind(path) == "data"


def test_classify_data_delete():
    path = [_edge("delete task")]
    assert _classify_goal_kind(path) == "data"


def test_classify_data_update():
    path = [_edge("update status")]
    assert _classify_goal_kind(path) == "data"


def test_classify_structural_search():
    path = [_edge("search employees")]
    assert _classify_goal_kind(path) == "structural"


def test_classify_structural_sort():
    path = [_edge("sort by date")]
    assert _classify_goal_kind(path) == "structural"


# ---------------------------------------------------------------------------
# _classify_data_verb
# ---------------------------------------------------------------------------

def test_data_verb_delete():
    path = [_edge("delete task")]
    assert _classify_data_verb(path) == "delete"


def test_data_verb_delete_beats_create():
    # delete keyword takes precedence (checked first in function)
    path = [_edge("delete and create")]
    assert _classify_data_verb(path) == "delete"


def test_data_verb_create():
    path = [_edge("add task")]
    assert _classify_data_verb(path) == "create"


def test_data_verb_update():
    path = [_edge("update task")]
    assert _classify_data_verb(path) == "update"


def test_data_verb_save():
    path = [_edge("save changes")]
    assert _classify_data_verb(path) == "update"


def test_data_verb_submit_is_create():
    path = [_edge("submit form")]
    assert _classify_data_verb(path) == "create"


def test_data_verb_defaults_create_when_unknown():
    path = [_edge("toggle switch")]
    assert _classify_data_verb(path) == "create"


# ---------------------------------------------------------------------------
# _ac_slots — fixed sets per goal kind
# ---------------------------------------------------------------------------

def test_slots_data():
    slots = _ac_slots("data")
    types = [s["type"] for s in slots]
    assert types == ["happy_path", "persistence", "edge_case"]
    fracs = [s["frac"] for s in slots]
    assert abs(sum(fracs) - 1.0) < 1e-9


def test_slots_structural():
    slots = _ac_slots("structural")
    types = [s["type"] for s in slots]
    assert types == ["happy_path", "edge_case"]
    fracs = [s["frac"] for s in slots]
    assert abs(sum(fracs) - 1.0) < 1e-9


def test_slots_navigation():
    slots = _ac_slots("navigation")
    assert [s["type"] for s in slots] == ["happy_path"]
    assert slots[0]["frac"] == 1.0


def test_slots_presence():
    slots = _ac_slots("presence")
    assert [s["type"] for s in slots] == ["happy_path"]


def test_slots_behavioral():
    slots = _ac_slots("behavioral")
    types = [s["type"] for s in slots]
    assert types == ["fires_when_due", "not_before_due"]
    fracs = [s["frac"] for s in slots]
    assert abs(sum(fracs) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# _compute_acws — sums exactly to weight
# ---------------------------------------------------------------------------

def _check_acws(slots, weight):
    acws = _compute_acws(slots, weight)
    assert len(acws) == len(slots)
    total = round(sum(acws), 10)
    assert abs(total - weight) < 1e-9, f"acws {acws} sum to {total}, expected {weight}"
    return acws


def test_acws_data_weight_3():
    slots = _ac_slots("data")
    _check_acws(slots, 3.0)


def test_acws_data_weight_4():
    slots = _ac_slots("data")
    _check_acws(slots, 4.0)


def test_acws_data_weight_1():
    slots = _ac_slots("data")
    _check_acws(slots, 1.0)


def test_acws_structural_weight_2():
    slots = _ac_slots("structural")
    _check_acws(slots, 2.0)


def test_acws_behavioral_weight_3():
    slots = _ac_slots("behavioral")
    _check_acws(slots, 3.0)


def test_acws_navigation_weight_3():
    slots = _ac_slots("navigation")
    acws = _check_acws(slots, 3.0)
    assert acws == [3.0]


def test_acws_presence_weight_4():
    slots = _ac_slots("presence")
    acws = _check_acws(slots, 4.0)
    assert acws == [4.0]


def test_acws_last_absorbs_rounding():
    # 3 slots with fracs 0.5, 0.3, 0.2 and weight=3.0:
    # 0.5×3=1.5, 0.3×3=0.9, last=3.0-1.5-0.9=0.6
    slots = _ac_slots("data")  # fracs 0.5 / 0.3 / 0.2
    acws = _compute_acws(slots, 3.0)
    assert acws[0] == 1.5
    assert acws[1] == 0.9
    assert abs(acws[2] - 0.6) < 1e-9


# ---------------------------------------------------------------------------
# _ac_id — sequential id format
# ---------------------------------------------------------------------------

def test_ac_id_req():
    assert _ac_id("REQ-001", 1) == "AC-001-1"
    assert _ac_id("REQ-001", 2) == "AC-001-2"


def test_ac_id_obv():
    assert _ac_id("OBV-001", 1) == "AC-OBV-001-1"


def test_ac_id_gen():
    assert _ac_id("GEN-005", 3) == "AC-GEN-005-3"


def test_ac_id_beh():
    assert _ac_id("BEH-001", 1) == "AC-BEH-001-1"
    assert _ac_id("BEH-001", 2) == "AC-BEH-001-2"


def test_ac_id_custom():
    assert _ac_id("CUSTOM-001", 1) == "AC-CUSTOM-001-1"


# ---------------------------------------------------------------------------
# _test_type — goal + strategy rule (never reads e_score)
# ---------------------------------------------------------------------------

def test_test_type_behavioral():
    assert _test_type("behavioral", {"primary": "Playwright E2E"}) == "behavioral"


def test_test_type_data_api_strategy():
    strategy = {"primary": "Pytest API tests", "secondary": None}
    assert _test_type("data", strategy) == "api"


def test_test_type_data_e2e_strategy():
    strategy = {"primary": "Playwright E2E", "secondary": "JUnit/MockMvc"}
    assert _test_type("data", strategy) == "e2e"


def test_test_type_navigation_is_always_e2e():
    strategy = {"primary": "Pytest API tests"}
    assert _test_type("navigation", strategy) == "e2e"


def test_test_type_presence_is_always_e2e():
    assert _test_type("presence", {"primary": "Supertest"}) == "e2e"


def test_test_type_structural_is_always_e2e():
    assert _test_type("structural", {"primary": "API tests"}) == "e2e"


def test_test_type_e2e_in_strategy_not_api():
    # strategy with "api" in name but also "e2e" → not api-only
    strategy = {"primary": "Playwright E2E with API checks"}
    assert _test_type("data", strategy) == "e2e"


# ---------------------------------------------------------------------------
# No Step 6 import in the module
# ---------------------------------------------------------------------------

def test_no_step6_import():
    import importlib.util
    import sys
    # Verify the module doesn't import step6_entity_mapper
    spec = importlib.util.find_spec("pipeline.step8_5_ac_generator")
    assert spec is not None
    src = open(spec.origin).read()
    assert "step6_entity_mapper" not in src
