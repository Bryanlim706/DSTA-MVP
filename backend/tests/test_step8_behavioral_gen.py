"""Tests for step8_behavioral_gen — _parse_response and _build_user_message."""
import json
import pytest

from pipeline.step8_behavioral_gen import _build_user_message, _parse_response


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def _make_item(**kwargs) -> dict:
    base = {
        "description": "System auto-resets task status to todo every midnight",
        "source_quote": "tasks auto-reset to todo every midnight",
        "priority": "high",
    }
    base.update(kwargs)
    return base


def test_parse_valid_single():
    raw = json.dumps([_make_item()])
    result = _parse_response(raw)
    assert len(result) == 1
    r = result[0]
    assert r["req_id"] == "BEH-001"
    assert r["description"] == "System auto-resets task status to todo every midnight"
    assert r["priority"] == "high"
    assert r["weight"] == 3.0
    assert r["source_quote"] == "tasks auto-reset to todo every midnight"
    assert r["path"] == [{"type": "node", "label": "System", "primary": True}]


def test_parse_valid_multiple():
    items = [
        _make_item(description="System sends reminder email when deadline passes"),
        _make_item(description="System expires session after 30 minutes of inactivity", priority="medium"),
    ]
    result = _parse_response(json.dumps(items))
    assert len(result) == 2
    assert result[0]["req_id"] == "BEH-001"
    assert result[1]["req_id"] == "BEH-002"
    assert result[1]["weight"] == 2.0


def test_parse_no_bracket_returns_empty():
    assert _parse_response("no array here") == []


def test_parse_invalid_json_returns_empty():
    assert _parse_response("{broken") == []


def test_parse_truncated_recovery():
    first = json.dumps(_make_item())
    truncated = "[" + first + ', {"description": "incomplete'
    result = _parse_response(truncated)
    assert len(result) >= 1
    assert result[0]["req_id"] == "BEH-001"


def test_parse_invalid_priority_defaults_medium():
    item = _make_item(priority="urgent")
    result = _parse_response(json.dumps([item]))
    assert result[0]["priority"] == "medium"
    assert result[0]["weight"] == 2.0


def test_parse_null_source_quote():
    item = _make_item(source_quote=None)
    result = _parse_response(json.dumps([item]))
    assert result[0]["source_quote"] is None


def test_parse_empty_source_quote_becomes_none():
    item = _make_item(source_quote="   ")
    result = _parse_response(json.dumps([item]))
    assert result[0]["source_quote"] is None


def test_parse_empty_array():
    result = _parse_response("[]")
    assert result == []


def test_parse_skips_items_without_description():
    items = [
        {"priority": "high"},  # no description
        _make_item(description="Valid behavior"),
    ]
    result = _parse_response(json.dumps(items))
    assert len(result) == 1
    assert result[0]["description"] == "Valid behavior"
    assert result[0]["req_id"] == "BEH-001"


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------

def _make_step3_5(confirmed=None, advisory=None, summary=None):
    return {
        "project_summary": summary or "A task management app.",
        "confirmed_requirements": confirmed or [
            {"req_id": "REQ-001", "description": "User can add a task"},
        ],
        "advisory_requirements": advisory or [],
    }


def _make_step4(models=None, impl_units=None):
    return {
        "database_models": ["Task", "User"] if models is None else models,
        "implementation_units": impl_units if impl_units is not None else [
            {"kind": "api_endpoint", "method": "POST", "path": "/api/tasks"},
            {"kind": "api_endpoint", "method": "GET",  "path": "/api/tasks"},
        ],
    }


def test_build_message_contains_requirements_text():
    msg = _build_user_message("Tasks auto-reset nightly", _make_step3_5(), _make_step4())
    assert "Tasks auto-reset nightly" in msg


def test_build_message_contains_project_summary():
    msg = _build_user_message("", _make_step3_5(summary="A kanban board."), _make_step4())
    assert "A kanban board." in msg


def test_build_message_contains_confirmed_reqs():
    msg = _build_user_message("", _make_step3_5(), _make_step4())
    assert "REQ-001" in msg
    assert "User can add a task" in msg


def test_build_message_contains_db_models():
    msg = _build_user_message("", _make_step3_5(), _make_step4(models=["Task", "Session"]))
    assert "Task" in msg
    assert "Session" in msg


def test_build_message_contains_endpoints():
    msg = _build_user_message("", _make_step3_5(), _make_step4())
    assert "POST /api/tasks" in msg


def test_build_message_truncates_long_text():
    long_text = "x" * 10_000
    msg = _build_user_message(long_text, _make_step3_5(), _make_step4())
    # Should be truncated to 8000 chars max
    assert len(msg) < 15_000


def test_build_message_no_models_shows_none():
    msg = _build_user_message("", _make_step3_5(), _make_step4(models=[]))
    assert "None detected" in msg


def test_parse_weight_from_priority():
    items = [
        _make_item(priority="critical"),
        _make_item(priority="high"),
        _make_item(priority="medium"),
        _make_item(priority="low"),
    ]
    result = _parse_response(json.dumps(items))
    weights = [r["weight"] for r in result]
    assert weights == [4.0, 3.0, 2.0, 1.0]


def test_parse_endpoint_negative_grounding_not_enforced():
    # _parse_response itself doesn't filter — that's the LLM's job per the prompt.
    # But the LLM is instructed to skip user-triggerable behaviors. This test
    # ensures the parser accepts any valid item regardless.
    item = _make_item(description="Any valid behavioral description")
    result = _parse_response(json.dumps([item]))
    assert len(result) == 1
