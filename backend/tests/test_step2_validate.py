"""Unit tests for step2_obvious_generator changes: depends_on, user message format, parser."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pipeline.step2_obvious_generator import _validate_and_normalise, _build_user_message, _parse_llm_response

STEP1 = [
    {"req_id": "REQ-001", "description": "System must allow users to log in", "functional_area": "auth"},
    {"req_id": "REQ-002", "description": "System must display a task list", "functional_area": "tasks"},
]


def test_depends_on_filters_invalid_ids():
    items = [
        {
            "description": "System must provide a way to navigate to the task list.",
            "reasoning": "CHECK 2 -- task list has no inbound navigation",
            "depends_on": ["REQ-002", "REQ-999"],
            "priority": "high",
            "functional_area": "navigation",
            "path": [{"type": "edge", "label": "navigate to task list", "from": "home", "to": "Task List", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1)
    assert len(valid) == 1
    assert valid[0]["depends_on"] == ["REQ-002"]
    assert valid[0]["req_id"] == "OBV-001"


def test_depends_on_empty_list_when_none_provided():
    items = [
        {
            "description": "System must provide exit navigation from login.",
            "reasoning": "CHECK 3 -- login has no exit path",
            "priority": "medium",
            "functional_area": "navigation",
            "path": [{"type": "edge", "label": "exit login", "from": "Login", "to": "home", "primary": True}],
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1)
    assert valid[0]["depends_on"] == []


def test_build_user_message_includes_req_ids():
    step0 = {
        "project_type": "full_stack_web_app",
        "frontend_framework": "React",
        "backend_framework": "Flask",
        "discovered_pages": ["login.html", "home.html"],
    }
    msg = _build_user_message(step0, STEP1)
    assert "[REQ-001]" in msg
    assert "[REQ-002]" in msg


def test_parse_llm_response_skips_preamble():
    import json
    items = [{"req_id": "OBV-001", "description": "nav", "reasoning": "CHECK 2"}]
    raw = "CHECK 1 reasoning...\nCHECK 2: YES\n" + json.dumps(items)
    parsed = _parse_llm_response(raw)
    assert len(parsed) == 1
    assert parsed[0]["description"] == "nav"


def test_duplicate_stated_dropped():
    items = [
        {
            "description": "System must allow users to log in",  # exact dup
            "reasoning": "CHECK 2 -- dup",
            "priority": "high",
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1)
    assert len(valid) == 0
    assert dropped == 1


def test_missing_reasoning_dropped():
    items = [
        {
            "description": "System must provide something.",
            "reasoning": "",
            "priority": "medium",
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1)
    assert len(valid) == 0
    assert dropped == 1


def test_check4_reasoning_dropped():
    items = [
        {
            "description": "System must display newly added items in the list.",
            "reasoning": "CHECK 4 — Add operation has no stated observable outcome.",
            "priority": "high",
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1)
    assert len(valid) == 0
    assert dropped == 1


def test_check5_reasoning_dropped():
    items = [
        {
            "description": "System must provide a button to mark a to-do item as complete.",
            "reasoning": "CHECK 5 — Complete capability has no stated UI control.",
            "priority": "high",
        }
    ]
    valid, dropped = _validate_and_normalise(items, STEP1)
    assert len(valid) == 0
    assert dropped == 1


def test_check2_and_check3_kept():
    items = [
        {
            "description": "System must provide a way to navigate to the Settings page.",
            "reasoning": "CHECK 2 — Settings page has no stated inbound navigation element.",
            "depends_on": ["REQ-001"],
            "priority": "critical",
            "path": [{"type": "edge", "label": "nav to settings", "from": "home", "to": "Settings", "primary": True}],
        },
        {
            "description": "System must provide a way to leave the Settings page.",
            "reasoning": "CHECK 3 — Settings page has no stated exit path.",
            "depends_on": [],
            "priority": "high",
            "path": [{"type": "edge", "label": "exit settings", "from": "Settings", "to": "home", "primary": True}],
        },
    ]
    valid, dropped = _validate_and_normalise(items, STEP1)
    assert len(valid) == 2
    assert dropped == 0


if __name__ == "__main__":
    test_depends_on_filters_invalid_ids()
    test_depends_on_empty_list_when_none_provided()
    test_build_user_message_includes_req_ids()
    test_parse_llm_response_skips_preamble()
    test_duplicate_stated_dropped()
    test_missing_reasoning_dropped()
    print("All step2 tests passed")
