"""Tests for step7_5_fa_advisor — _parse_response and _build_user_message."""

import json
import pytest

from pipeline.step7_5_fa_advisor import _build_user_message, _parse_response


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def _make_item(**kwargs) -> dict:
    base = {
        "suggestion_id": "FA-POS-001",
        "description": "User can view team tasks",
        "grounded_in": {
            "models": ["Task", "User"],
            "endpoints": ["GET /api/tasks"],
            "rationale": "Task has team_id FK",
        },
        "l1a_connection": "REQ-003",
        "priority": "medium",
    }
    base.update(kwargs)
    return base


def test_parse_response_valid_single():
    raw = json.dumps([_make_item()])
    result = _parse_response(raw)
    assert len(result) == 1
    s = result[0]
    assert s["description"] == "User can view team tasks"
    assert s["grounded_in"]["models"] == ["Task", "User"]
    assert s["grounded_in"]["endpoints"] == ["GET /api/tasks"]
    assert s["priority"] == "medium"
    assert s["l1a_connection"] == "REQ-003"


def test_parse_response_valid_multiple():
    items = [
        _make_item(suggestion_id="FA-POS-001", description="User can filter by team"),
        _make_item(suggestion_id="FA-POS-002", description="User can export tasks"),
    ]
    result = _parse_response(json.dumps(items))
    assert len(result) == 2
    assert result[0]["description"] == "User can filter by team"
    assert result[1]["description"] == "User can export tasks"


def test_parse_response_no_bracket_returns_empty():
    result = _parse_response("no array here")
    assert result == []


def test_parse_response_invalid_json_returns_empty():
    result = _parse_response("{broken json")
    assert result == []


def test_parse_response_truncated_recovery():
    # First item is complete JSON; second item is cut off mid-string — recovery must find the
    # "}, " separator and recover the first item.
    first = json.dumps(_make_item(suggestion_id="FA-POS-001"))
    truncated = "[" + first + ', {"description": "incomplete'
    result = _parse_response(truncated)
    assert len(result) >= 1
    assert result[0]["description"] == "User can view team tasks"


def test_parse_response_fixes_invalid_suggestion_id():
    item = _make_item(suggestion_id="INVALID-001")
    result = _parse_response(json.dumps([item]))
    assert len(result) == 1
    # Should get a generated FA-POS-001
    assert result[0]["suggestion_id"] == "FA-POS-001"


def test_parse_response_normalises_bad_priority():
    item = _make_item(priority="critical")
    result = _parse_response(json.dumps([item]))
    assert result[0]["priority"] == "medium"


def test_parse_response_keeps_valid_priorities():
    for p in ("high", "medium", "low"):
        item = _make_item(priority=p)
        result = _parse_response(json.dumps([item]))
        assert result[0]["priority"] == p


def test_parse_response_null_string_l1a_connection_becomes_none():
    item = _make_item(l1a_connection="null")
    result = _parse_response(json.dumps([item]))
    assert result[0]["l1a_connection"] is None


def test_parse_response_skips_items_without_description():
    items = [
        {"suggestion_id": "FA-POS-001", "description": ""},  # empty — should be dropped
        _make_item(suggestion_id="FA-POS-002", description="User can do X"),
    ]
    result = _parse_response(json.dumps(items))
    assert len(result) == 1
    assert result[0]["description"] == "User can do X"


def test_parse_response_skips_non_dict_items():
    mixed = ["not a dict", _make_item(), 42]
    result = _parse_response(json.dumps(mixed))
    assert len(result) == 1
    assert result[0]["description"] == "User can view team tasks"


def test_parse_response_missing_grounded_in_defaults():
    item = {
        "suggestion_id": "FA-POS-001",
        "description": "User can archive tasks",
        "priority": "low",
    }
    result = _parse_response(json.dumps([item]))
    assert len(result) == 1
    assert result[0]["grounded_in"]["models"] == []
    assert result[0]["grounded_in"]["endpoints"] == []
    assert result[0]["grounded_in"]["rationale"] == ""


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------

def _make_step3_5(l1a=None, l1b=None):
    return {
        "project_summary": "A task management app for teams.",
        "confirmed_requirements": l1a or [
            {"req_id": "REQ-001", "description": "User can log in"},
            {"req_id": "REQ-002", "description": "User can create a task"},
        ],
        "advisory_requirements": l1b or [
            {"req_id": "GEN-001", "description": "User can filter tasks"},
        ],
    }


def _make_step4(models=None, endpoints=None, routes=None):
    if models is None:
        models = ["Task", "User"]
    if endpoints is None:
        endpoints = [("GET", "/api/tasks"), ("POST", "/api/tasks")]
    if routes is None:
        routes = ["/", "/tasks"]
    return {
        "database_models": models,
        "implementation_units": [
            {"kind": "api_endpoint", "method": m, "path": p, "file": "f", "handler": "h"}
            for m, p in endpoints
        ],
        "frontend_routes": [{"path": r, "dynamic": False, "params": []} for r in routes],
    }


def _make_step5(pages=None):
    return {
        "pages": pages or [
            {
                "route": "/tasks",
                "accessible": True,
                "discovered_by": "playwright",
                "elements": [
                    {"type": "button", "label": "Add Task"},
                    {"type": "input", "label": "Task name"},
                ],
                "outbound_links": [],
                "api_calls_observed": [],
            }
        ]
    }


def test_build_user_message_contains_project_summary():
    msg = _build_user_message(_make_step3_5(), _make_step4(), _make_step5())
    assert "task management app for teams" in msg


def test_build_user_message_contains_l1a_requirements():
    msg = _build_user_message(_make_step3_5(), _make_step4(), _make_step5())
    assert "REQ-001" in msg
    assert "User can log in" in msg


def test_build_user_message_contains_l1b_requirements():
    msg = _build_user_message(_make_step3_5(), _make_step4(), _make_step5())
    assert "GEN-001" in msg
    assert "User can filter tasks" in msg


def test_build_user_message_contains_models():
    msg = _build_user_message(_make_step3_5(), _make_step4(), _make_step5())
    assert "Task" in msg
    assert "User" in msg


def test_build_user_message_contains_endpoints():
    msg = _build_user_message(_make_step3_5(), _make_step4(), _make_step5())
    assert "GET /api/tasks" in msg
    assert "POST /api/tasks" in msg


def test_build_user_message_contains_frontend_routes():
    msg = _build_user_message(_make_step3_5(), _make_step4(), _make_step5())
    assert "/tasks" in msg


def test_build_user_message_contains_page_elements():
    msg = _build_user_message(_make_step3_5(), _make_step4(), _make_step5())
    assert "Add Task" in msg


def test_build_user_message_caps_endpoints_at_40():
    many_endpoints = [(f"GET", f"/api/item{i}") for i in range(60)]
    step4 = _make_step4(endpoints=many_endpoints)
    msg = _build_user_message(_make_step3_5(), step4, _make_step5())
    # Only first 40 endpoints should appear (GET /api/item0 through /api/item39)
    assert "GET /api/item39" in msg
    assert "GET /api/item40" not in msg


def test_build_user_message_caps_l1b_at_25():
    many_l1b = [{"req_id": f"GEN-{i:03d}", "description": f"User can do thing {i}"} for i in range(30)]
    step3_5 = _make_step3_5(l1b=many_l1b)
    msg = _build_user_message(step3_5, _make_step4(), _make_step5())
    assert "GEN-024" in msg  # index 24 (25th item) is included
    assert "GEN-025" not in msg  # index 25 (26th item) is excluded


def test_build_user_message_empty_models_says_none_detected():
    step4 = _make_step4(models=[])
    msg = _build_user_message(_make_step3_5(), step4, _make_step5())
    assert "None detected" in msg


def test_build_user_message_no_page_elements_skips_section():
    step5 = {"pages": [{"route": "/tasks", "accessible": True, "discovered_by": "playwright",
                         "elements": [], "outbound_links": [], "api_calls_observed": []}]}
    msg = _build_user_message(_make_step3_5(), _make_step4(), step5)
    assert "Live UI Elements" not in msg
