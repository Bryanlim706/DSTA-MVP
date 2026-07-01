import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.step6_entity_mapper import (
    _aggregate,
    _build_nav_inventory,
    _build_page_inventory,
    _candidate_routes,
    _compute_unlinked,
    _parse_grounding_response,
    _score_entity,
)


# ---------------------------------------------------------------------------
# _build_page_inventory
# ---------------------------------------------------------------------------

def test_build_page_inventory_playwright_accessible():
    pages = [{
        "route": "/login",
        "accessible": True,
        "discovered_by": "playwright",
        "elements": [{"type": "input", "label": "email", "selector": "input[type=email]"}],
        "outbound_links": [],
        "api_calls_observed": [],
    }]
    route_elements = {}
    inv = _build_page_inventory(pages, route_elements)
    assert inv["/login"]["source"] == "playwright"
    assert inv["/login"]["elements"][0]["label"] == "email"


def test_build_page_inventory_static_fallback_uses_route_elements():
    pages = [{
        "route": "/dashboard",
        "accessible": None,
        "discovered_by": "static_fallback",
        "elements": [],
        "outbound_links": [],
        "api_calls_observed": [],
    }]
    route_elements = {"/dashboard": [{"type": "button", "label": "Add Item", "subtype": None}]}
    inv = _build_page_inventory(pages, route_elements)
    assert inv["/dashboard"]["source"] == "route_elements"
    assert any(e["label"] == "Add Item" for e in inv["/dashboard"]["elements"])


def test_build_page_inventory_auth_gated_uses_route_elements():
    pages = [{
        "route": "/admin",
        "accessible": False,
        "discovered_by": "playwright",
        "elements": [],
        "outbound_links": [],
        "api_calls_observed": [],
    }]
    route_elements = {"/admin": [{"type": "button", "label": "Manage Users", "subtype": None}]}
    inv = _build_page_inventory(pages, route_elements)
    assert inv["/admin"]["source"] == "route_elements"


def test_build_page_inventory_supplement_from_route_elements():
    pages = []
    route_elements = {"/products": [{"type": "button", "label": "Add Product", "subtype": None}]}
    inv = _build_page_inventory(pages, route_elements)
    assert "/products" in inv
    assert inv["/products"]["source"] == "route_elements"


def test_build_page_inventory_empty_route_elements_source_none():
    pages = [{
        "route": "/about",
        "accessible": False,
        "discovered_by": "static_fallback",
        "elements": [],
        "outbound_links": [],
        "api_calls_observed": [],
    }]
    route_elements = {}
    inv = _build_page_inventory(pages, route_elements)
    assert inv["/about"]["source"] == "none"


# ---------------------------------------------------------------------------
# _build_nav_inventory
# ---------------------------------------------------------------------------

def test_build_nav_inventory_merges_graph_and_outbound():
    nav_graph = {"/login": ["/dashboard"]}
    pages = [{
        "route": "/login",
        "outbound_links": ["/home", "/dashboard"],
    }]
    nav = _build_nav_inventory(nav_graph, pages)
    assert "/dashboard" in nav["/login"]
    assert "/home" in nav["/login"]
    # No duplicates
    assert nav["/login"].count("/dashboard") == 1


def test_build_nav_inventory_page_without_graph_entry():
    nav_graph = {}
    pages = [{"route": "/cart", "outbound_links": ["/checkout"]}]
    nav = _build_nav_inventory(nav_graph, pages)
    assert "/checkout" in nav["/cart"]


# ---------------------------------------------------------------------------
# _candidate_routes
# ---------------------------------------------------------------------------

def test_candidate_routes_login_page():
    path = [{"type": "node", "label": "Login Page"}]
    routes = ["/", "/login", "/dashboard", "/products"]
    candidates = _candidate_routes(path, routes)
    assert "/login" in candidates


def test_candidate_routes_home_node():
    path = [{"type": "node", "label": "Home"}]
    routes = ["/", "/about", "/products"]
    candidates = _candidate_routes(path, routes)
    assert "/" in candidates


def test_candidate_routes_no_nodes_returns_all():
    path = [{"type": "element", "label": "Submit"}]
    routes = ["/a", "/b", "/c"]
    candidates = _candidate_routes(path, routes)
    assert set(candidates) == {"/a", "/b", "/c"}


def test_candidate_routes_always_includes_root():
    path = [{"type": "node", "label": "Dashboard"}]
    routes = ["/", "/dashboard"]
    candidates = _candidate_routes(path, routes)
    assert "/" in candidates


# ---------------------------------------------------------------------------
# _parse_grounding_response
# ---------------------------------------------------------------------------

def test_parse_grounding_valid_json():
    raw = '[{"entity_index": 0, "type": "node", "matched_route": "/login"}]'
    result = _parse_grounding_response(raw, 1)
    assert result[0]["matched_route"] == "/login"


def test_parse_grounding_markdown_block():
    raw = '```json\n[{"entity_index": 0, "type": "node", "matched_route": "/home"}]\n```'
    result = _parse_grounding_response(raw, 1)
    assert result[0]["matched_route"] == "/home"


def test_parse_grounding_leading_text():
    raw = 'Here is my analysis:\n[{"entity_index": 0, "type": "element", "matched_element_label": "email"}]'
    result = _parse_grounding_response(raw, 1)
    assert result[0].get("matched_element_label") == "email"


def test_parse_grounding_invalid_json_returns_empty_list():
    result = _parse_grounding_response("not json at all", 3)
    assert result == [{}, {}, {}]


def test_parse_grounding_out_of_range_index_ignored():
    raw = '[{"entity_index": 99, "type": "node", "matched_route": "/x"}]'
    result = _parse_grounding_response(raw, 2)
    assert result == [{}, {}]


def test_parse_grounding_pads_missing_entities():
    raw = '[{"entity_index": 0, "type": "node", "matched_route": "/login"}]'
    result = _parse_grounding_response(raw, 3)
    assert len(result) == 3
    assert result[1] == {}
    assert result[2] == {}


# ---------------------------------------------------------------------------
# _score_entity
# ---------------------------------------------------------------------------

_PAGE_INV = {
    "/login": {"source": "playwright", "elements": [
        {"label": "Enter email", "type": "input", "selector": "input[type=email]"},
    ]},
    "/dashboard": {"source": "route_elements", "elements": [
        {"label": "Add Task", "type": "button"},
    ]},
}


def test_score_entity_node_accessible():
    entity = {"type": "node", "label": "Login Page", "primary": True}
    grounding = {"matched_route": "/login"}
    e, extra = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 1.0
    assert extra["matched_route"] == "/login"


def test_score_entity_node_static_fallback():
    entity = {"type": "node", "label": "Dashboard", "primary": True}
    grounding = {"matched_route": "/dashboard"}
    e, extra = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.5


def test_score_entity_node_not_found():
    entity = {"type": "node", "label": "Unknown Page", "primary": True}
    grounding = {"matched_route": None}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.0


def test_score_entity_node_matched_route_not_in_inventory():
    entity = {"type": "node", "label": "Ghost", "primary": True}
    grounding = {"matched_route": "/ghost"}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.0


def test_score_entity_element_playwright():
    entity = {"type": "element", "label": "email input", "primary": True}
    grounding = {"matched_element_label": "Enter email", "match_source": "playwright"}
    e, extra = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 1.0
    assert extra["matched_selector"] == "input[type=email]"


def test_score_entity_element_route_elements():
    entity = {"type": "element", "label": "add task button", "primary": True}
    grounding = {"matched_element_label": "Add Task", "match_source": "route_elements"}
    e, extra = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.75
    assert extra["match_source"] == "route_elements"


def test_score_entity_element_not_found():
    entity = {"type": "element", "label": "missing", "primary": True}
    grounding = {"matched_element_label": None, "match_source": None}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.0


def test_score_entity_data_edge_both_found():
    entity = {"type": "data_edge", "label": "submit login", "primary": True}
    grounding = {
        "matched_endpoint": "POST /api/auth/login",
        "trigger_element_label": "Login button",
    }
    e, extra = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 1.0
    assert extra["matched_endpoint"] == "POST /api/auth/login"


def test_score_entity_data_edge_endpoint_only():
    entity = {"type": "data_edge", "label": "submit login", "primary": True}
    grounding = {"matched_endpoint": "POST /api/auth/login", "trigger_element_label": None}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.75


def test_score_entity_data_edge_trigger_only():
    entity = {"type": "data_edge", "label": "delete item", "primary": True}
    grounding = {"matched_endpoint": None, "trigger_element_label": "Delete"}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.4


def test_score_entity_data_edge_neither():
    entity = {"type": "data_edge", "label": "create order", "primary": True}
    grounding = {"matched_endpoint": None, "trigger_element_label": None}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.0


def test_score_entity_navigation_playwright_element():
    entity = {"type": "navigation_edge", "label": "navigate to dashboard", "primary": True}
    grounding = {"matched_nav_target": "/dashboard", "match_source": "playwright_element"}
    e, extra = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 1.0
    assert extra["matched_nav_target"] == "/dashboard"


def test_score_entity_navigation_graph():
    entity = {"type": "navigation_edge", "label": "go to home", "primary": True}
    grounding = {"matched_nav_target": "/", "match_source": "navigation_graph"}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.75


def test_score_entity_navigation_not_found():
    entity = {"type": "navigation_edge", "label": "open cart", "primary": True}
    grounding = {"matched_nav_target": None, "match_source": None}
    e, _ = _score_entity(entity, grounding, _PAGE_INV)
    assert e == 0.0


# ---------------------------------------------------------------------------
# _aggregate
# ---------------------------------------------------------------------------

def test_aggregate_all_primary():
    scores = [
        {"primary": True, "e": 1.0},
        {"primary": True, "e": 0.5},
    ]
    result = _aggregate(scores)
    assert result == 0.75


def test_aggregate_primary_and_secondary():
    # 0.7 * 1.0 + 0.3 * 0.0 = 0.7
    scores = [
        {"primary": True, "e": 1.0},
        {"primary": False, "e": 0.0},
    ]
    result = _aggregate(scores)
    assert abs(result - 0.7) < 1e-9


def test_aggregate_all_secondary():
    scores = [{"primary": False, "e": 0.5}]
    assert _aggregate(scores) == 0.5


def test_aggregate_empty():
    assert _aggregate([]) == 0.0


def test_aggregate_none_e_skipped():
    scores = [
        {"primary": True, "e": None},
        {"primary": True, "e": 1.0},
    ]
    result = _aggregate(scores)
    assert result == 1.0


def test_aggregate_formula_exact():
    # primary: [1.0, 0.5] avg=0.75; secondary: [0.0] avg=0.0
    # 0.7*0.75 + 0.3*0.0 = 0.525
    scores = [
        {"primary": True, "e": 1.0},
        {"primary": True, "e": 0.5},
        {"primary": False, "e": 0.0},
    ]
    result = _aggregate(scores)
    assert abs(result - 0.525) < 1e-9


# ---------------------------------------------------------------------------
# _compute_unlinked
# ---------------------------------------------------------------------------

def test_compute_unlinked_l2_accessible_not_matched():
    l1a_reqs = [{"req_id": "REQ-001"}]
    mapped = [{
        "req_id": "REQ-001",
        "entity_scores": [
            {"type": "node", "primary": True, "e": 1.0, "matched_route": "/login"},
        ],
    }]
    step5_pages = [
        {"route": "/login", "accessible": True, "title": "Login"},
        {"route": "/admin", "accessible": True, "title": "Admin"},
    ]
    impl_units = []
    unlinked_l2, unlinked_l3 = _compute_unlinked(l1a_reqs, mapped, step5_pages, impl_units)
    assert len(unlinked_l2) == 1
    assert unlinked_l2[0]["route"] == "/admin"


def test_compute_unlinked_l2_inaccessible_excluded():
    l1a_reqs = []
    mapped = []
    step5_pages = [{"route": "/secret", "accessible": False, "title": None}]
    unlinked_l2, _ = _compute_unlinked(l1a_reqs, mapped, step5_pages, [])
    assert unlinked_l2 == []


def test_compute_unlinked_l3_endpoint_not_matched():
    l1a_reqs = [{"req_id": "REQ-001"}]
    mapped = [{
        "req_id": "REQ-001",
        "entity_scores": [
            {"type": "data_edge", "matched_endpoint": "POST /api/login"},
        ],
    }]
    impl_units = [
        {"kind": "api_endpoint", "method": "POST", "path": "/api/login", "handler": "login", "file": "auth.py"},
        {"kind": "api_endpoint", "method": "DELETE", "path": "/api/users/1", "handler": "delete_user", "file": "users.py"},
    ]
    _, unlinked_l3 = _compute_unlinked(l1a_reqs, mapped, [], impl_units)
    assert len(unlinked_l3) == 1
    assert unlinked_l3[0]["path"] == "/api/users/1"


def test_compute_unlinked_l3_form_handlers_excluded():
    l1a_reqs = []
    mapped = []
    impl_units = [
        {"kind": "form_handler", "method": "POST", "path": "/submit", "handler": None, "file": "index.html"},
    ]
    _, unlinked_l3 = _compute_unlinked(l1a_reqs, mapped, [], impl_units)
    assert unlinked_l3 == []


def test_compute_unlinked_l1b_not_in_unlinked():
    """L1b requirements are not counted as L1a, so their matched routes don't prevent L2 unlinked."""
    l1a_reqs = []
    l1b_mapped = [{
        "req_id": "GEN-001",  # L1b req
        "entity_scores": [
            {"type": "node", "primary": True, "e": 1.0, "matched_route": "/admin"},
        ],
    }]
    step5_pages = [{"route": "/admin", "accessible": True, "title": "Admin"}]
    unlinked_l2, _ = _compute_unlinked(l1a_reqs, l1b_mapped, step5_pages, [])
    assert any(u["route"] == "/admin" for u in unlinked_l2)


# ---------------------------------------------------------------------------
# Fix: dot-notation label filtering
# ---------------------------------------------------------------------------

def test_build_page_inventory_filters_dot_notation_from_extra():
    """Dot-notation labels like 'product.name' must be excluded from merged extra elements."""
    pages = [{
        "route": "/add",
        "accessible": True,
        "discovered_by": "playwright",
        "elements": [{"type": "input", "label": "Product Name", "selector": "input"}],
        "outbound_links": [],
        "api_calls_observed": [],
    }]
    route_elements = {"/add": [
        {"type": "input", "label": "product.name", "subtype": "text"},
        {"type": "button", "label": "Submit", "subtype": "submit"},
    ]}
    inv = _build_page_inventory(pages, route_elements)
    labels = [e["label"] for e in inv["/add"]["elements"]]
    assert "product.name" not in labels   # dot-notation filtered
    assert "Submit" in labels             # real label kept
    assert "Product Name" in labels       # playwright element kept


def test_build_page_inventory_filters_dot_notation_from_route_elements_only():
    """Dot-notation labels are also filtered from route_elements-only pages."""
    pages = []
    route_elements = {"/update": [
        {"type": "input", "label": "updateProduct.name", "subtype": "text"},
        {"type": "button", "label": "Update", "subtype": "submit"},
    ]}
    inv = _build_page_inventory(pages, route_elements)
    labels = [e["label"] for e in inv["/update"]["elements"]]
    assert "updateProduct.name" not in labels
    assert "Update" in labels


# ---------------------------------------------------------------------------
# Fix: form-confirmation promotion (controlled-input label mismatch)
# ---------------------------------------------------------------------------

def test_build_page_inventory_promotes_form_labels_when_playwright_confirmed_form():
    """When Playwright found genuine form inputs, route_elements form entries are promoted
    to playwright source — handles controlled React inputs (name attr vs placeholder)."""
    pages = [{
        "route": "/update",
        "accessible": True,
        "discovered_by": "playwright",
        "elements": [
            # Playwright found form inputs by name attribute
            {"type": "input", "subtype": "text",   "label": "name",   "selector": "#name"},
            {"type": "input", "subtype": "number", "label": "price",  "selector": "#price"},
            {"type": "button", "subtype": "submit", "label": "Submit", "selector": "button"},
        ],
        "outbound_links": [],
        "api_calls_observed": [],
    }]
    # route_elements has descriptive placeholder labels for the same fields
    route_elements = {"/update": [
        {"type": "input", "subtype": "text",   "label": "Product Name"},
        {"type": "input", "subtype": "number", "label": "Price"},
        {"type": "button", "subtype": "None",  "label": "Delete"},  # button — not promoted
    ]}
    inv = _build_page_inventory(pages, route_elements)
    pw_labels = inv["/update"]["_playwright_labels"]
    # Descriptive form labels promoted because Playwright confirmed form inputs exist
    assert "Product Name" in pw_labels
    assert "Price" in pw_labels
    # Button extras are NOT promoted (only form controls promoted)
    assert "Delete" not in pw_labels


def test_build_page_inventory_does_not_promote_when_no_form_inputs():
    """When Playwright found only nav/search (no form inputs), no promotion occurs."""
    pages = [{
        "route": "/products",
        "accessible": True,
        "discovered_by": "playwright",
        "elements": [
            {"type": "link",  "subtype": None,     "label": "Home",   "selector": "a"},
            {"type": "input", "subtype": "search",  "label": "Search", "selector": "input"},
        ],
        "outbound_links": [],
        "api_calls_observed": [],
    }]
    route_elements = {"/products": [
        {"type": "input", "subtype": "text", "label": "Product Name"},
    ]}
    inv = _build_page_inventory(pages, route_elements)
    pw_labels = inv["/products"]["_playwright_labels"]
    # No promotion — only search input present, no genuine form confirmed
    assert "Product Name" not in pw_labels
