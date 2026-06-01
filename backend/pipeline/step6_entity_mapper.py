import asyncio
import json
import re

import anthropic

MODEL = "claude-haiku-4-5-20251001"

_DATA_KEYWORDS = frozenset([
    "submit", "add", "create", "delete", "remove", "update", "save", "mark",
    "complete", "pause", "resume", "sync", "upload", "download", "move",
    "configure", "change", "reset", "toggle",
])
_STRUCTURAL_KEYWORDS = frozenset(["filter", "search", "sort", "drag", "drop", "reorder"])

LLM_SYSTEM_PROMPT = """You are a requirement-to-implementation matcher.

Given a software requirement with a traversal path and a code/runtime inventory, identify which inventory items correspond to each path entity.

Output a JSON array — one object per path entity, in order, indexed by "entity_index" (0-based).

Object schema by entity type:

node:
  {"entity_index": N, "type": "node", "matched_route": "/path" | null}

element:
  {"entity_index": N, "type": "element", "matched_element_label": "label" | null, "match_source": "playwright" | "route_elements" | null}

edge with edge_kind "data":
  {"entity_index": N, "type": "edge", "edge_kind": "data", "matched_endpoint": "METHOD /path" | null, "trigger_element_label": "label" | null}

edge with edge_kind "navigation":
  {"entity_index": N, "type": "edge", "edge_kind": "navigation", "matched_nav_target": "/path" | null, "match_source": "playwright_element" | "navigation_graph" | null}

edge with edge_kind "structural":
  {"entity_index": N, "type": "edge", "edge_kind": "structural", "trigger_element_label": "label" | null, "match_source": "playwright" | "route_elements" | null}

Matching rules:
1. ONLY match items explicitly present in the inventory. Set null if not found.
2. node: match the label to a route path by semantic similarity (e.g. "Login Page" → "/login", "Home" → "/").
3. element: after resolving a nearby node entity, search that route's element inventory for the best label match. Copy the inventory source label ("playwright" or "route_elements") into match_source.
4. edge/data: match to implementation_units using the edge label to infer HTTP verb (submit/add/create → POST, delete/remove → DELETE, update/edit/save → PATCH or PUT). Return "METHOD /path" format.
5. edge/navigation: check if a rendered link or button in the element inventory navigates to a matching target route → "playwright_element"; otherwise check the static navigation_graph → "navigation_graph".
6. edge/structural: find a triggering element (filter input, search box, sort button, etc.) in the element inventory. Copy the inventory source into match_source.
7. Always output exactly N objects, one per entity, maintaining index order."""


def _classify_edge_kind(label: str) -> str:
    words = set(re.findall(r"\b\w+\b", label.lower()))
    if words & _DATA_KEYWORDS:
        return "data"
    if words & _STRUCTURAL_KEYWORDS:
        return "structural"
    return "navigation"


def _build_page_inventory(step5_pages: list, route_elements: dict) -> dict:
    """Return {route: {elements: [...], source: playwright|route_elements|none}}."""
    inventory: dict = {}

    for page in step5_pages:
        route = page.get("route", "")
        if not route:
            continue
        if page.get("accessible") is True and page.get("discovered_by") == "playwright":
            inventory[route] = {"elements": page.get("elements", []), "source": "playwright"}
        else:
            fallback = route_elements.get(route, [])
            inventory[route] = {
                "elements": [
                    {"label": e.get("label", ""), "type": e.get("type", ""), "subtype": e.get("subtype")}
                    for e in fallback
                ],
                "source": "route_elements" if fallback else "none",
            }

    # Routes only in Step 4 route_elements (not visited by Step 5 at all)
    for route, elems in route_elements.items():
        if route not in inventory and elems:
            inventory[route] = {
                "elements": [
                    {"label": e.get("label", ""), "type": e.get("type", ""), "subtype": e.get("subtype")}
                    for e in elems
                ],
                "source": "route_elements",
            }

    return inventory


def _build_nav_inventory(navigation_graph: dict, step5_pages: list) -> dict:
    """Return {route: [target_routes]} merging Step 4 nav_graph + Step 5 outbound_links."""
    nav: dict = {}
    for route, targets in navigation_graph.items():
        nav[route] = list(targets)
    for page in step5_pages:
        route = page.get("route", "")
        if not route:
            continue
        if route not in nav:
            nav[route] = []
        for link in page.get("outbound_links", []):
            if link not in nav[route]:
                nav[route].append(link)
    return nav


def _candidate_routes(path: list, route_paths: list) -> list:
    """Heuristically select relevant routes for this requirement's inventory scoping."""
    node_labels = [e.get("label", "").lower() for e in path if e.get("type") == "node"]
    if not node_labels:
        return route_paths[:10]

    candidates: list = []
    home_words = {"home", "landing", "main", "index", "root"}

    for label in node_labels:
        label_clean = re.sub(r"\b(page|screen|view|panel|list|detail)\b", "", label).strip()
        for route in route_paths:
            route_base = (
                route.lstrip("/").replace("-", " ").replace("_", " ").replace("/", " ").lower().strip()
            )
            if route_base and (route_base in label_clean or label_clean in route_base):
                if route not in candidates:
                    candidates.append(route)
            elif route == "/" and any(w in label for w in home_words):
                if route not in candidates:
                    candidates.append(route)

    if "/" in route_paths and "/" not in candidates:
        candidates.append("/")

    return candidates if candidates else route_paths[:10]


def _build_grounding_user_message(
    req: dict,
    frontend_routes: list,
    page_inventory: dict,
    nav_inventory: dict,
    impl_units: list,
) -> str:
    path = req.get("path", [])
    desc = req.get("description", "")

    lines = [f"Requirement: {desc}", "", "Path entities:"]
    for i, entity in enumerate(path):
        etype = entity.get("type", "")
        label = entity.get("label", "")
        primary = "primary" if entity.get("primary", True) else "secondary"
        if etype == "edge":
            ek = _classify_edge_kind(label)
            lines.append(f'[{i}] type: edge, edge_kind: {ek}, label: "{label}", {primary}')
        else:
            lines.append(f'[{i}] type: {etype}, label: "{label}", {primary}')

    route_paths = [r.get("path", "") if isinstance(r, dict) else str(r) for r in frontend_routes]
    dynamic_routes = {
        r.get("path", "") for r in frontend_routes if isinstance(r, dict) and r.get("dynamic")
    }
    candidates = _candidate_routes(path, route_paths)

    lines.append("")
    lines.append("Available routes:")
    for r in route_paths:
        flag = " (dynamic)" if r in dynamic_routes else ""
        lines.append(f"- {r}{flag}")

    lines.append("")
    lines.append("Element inventory (by route):")
    shown_any = False
    for route in candidates:
        inv = page_inventory.get(route, {})
        elements = inv.get("elements", [])
        source = inv.get("source", "none")
        if not elements:
            continue
        shown_any = True
        lines.append(f"=== {route} [source: {source}] ===")
        for elem in elements[:20]:
            lbl = elem.get("label") or ""
            et = elem.get("type", "?")
            sub = elem.get("subtype") or ""
            sel = elem.get("selector") or ""
            type_str = f"{et}[{sub}]" if sub else et
            if sel:
                lines.append(f'  - {type_str}: "{lbl}" (selector: {sel})')
            else:
                lines.append(f'  - {type_str}: "{lbl}"')
    if not shown_any:
        lines.append("  (no elements in inventory for candidate routes)")

    has_data = any(
        e.get("type") == "edge" and _classify_edge_kind(e.get("label", "")) == "data"
        for e in path
    )
    if has_data or not path:
        lines.append("")
        lines.append("Implementation units (backend endpoints):")
        api_units = [u for u in impl_units if u.get("kind") == "api_endpoint"]
        if api_units:
            for u in api_units[:40]:
                method = u.get("method", "?")
                upath = u.get("path") or "?"
                handler = u.get("handler") or ""
                lines.append(f"  - {method} {upath}" + (f" ({handler})" if handler else ""))
        else:
            lines.append("  (none detected)")

    has_nav = any(
        e.get("type") == "edge" and _classify_edge_kind(e.get("label", "")) == "navigation"
        for e in path
    )
    if has_nav or not path:
        lines.append("")
        lines.append("Navigation targets (from candidate routes):")
        any_nav = False
        for route in candidates:
            targets = nav_inventory.get(route, [])
            if targets:
                any_nav = True
                lines.append(f"  From {route}: " + ", ".join(str(t) for t in targets[:10]))
        if not any_nav:
            lines.append("  (none detected)")

    return "\n".join(lines)


def _parse_grounding_response(raw: str, num_entities: int) -> list:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        bracket_pos = text.find("[")
        if bracket_pos > 0:
            text = text[bracket_pos:]

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return [{}] * num_entities

    if not isinstance(items, list):
        return [{}] * num_entities

    result: list = [{}] * num_entities
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("entity_index")
        if isinstance(idx, int) and 0 <= idx < num_entities:
            result[idx] = item

    return result


async def _ground_requirement(
    req: dict,
    frontend_routes: list,
    page_inventory: dict,
    nav_inventory: dict,
    impl_units: list,
    client: anthropic.AsyncAnthropic,
) -> list:
    path = req.get("path", [])
    if not path:
        return []

    user_msg = _build_grounding_user_message(
        req, frontend_routes, page_inventory, nav_inventory, impl_units
    )
    last_exc: Exception | None = None

    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=[{
                    "type": "text",
                    "text": LLM_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_msg}],
            )
            return _parse_grounding_response(response.content[0].text, len(path))
        except anthropic.APIStatusError as exc:
            last_exc = exc
            if exc.status_code == 529 and attempt < 2:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last_exc = exc
            break

    return [{}] * len(path)


def _lookup_selector(matched_label: str | None, page_inventory: dict) -> str | None:
    if not matched_label:
        return None
    for inv in page_inventory.values():
        for elem in inv.get("elements", []):
            if elem.get("label") == matched_label:
                sel = elem.get("selector")
                if sel:
                    return sel
    return None


def _score_entity(entity: dict, grounding: dict, page_inventory: dict) -> tuple[float, dict]:
    etype = entity.get("type", "")
    extra: dict = {}

    if etype == "node":
        matched_route = grounding.get("matched_route")
        extra["matched_route"] = matched_route
        if not matched_route:
            e = 0.0
            extra["evidence"] = "route not found in inventory"
        else:
            source = page_inventory.get(matched_route, {}).get("source", "none")
            if source == "playwright":
                e = 1.0
                extra["evidence"] = "route found + page accessible (Playwright)"
            elif source == "route_elements":
                e = 0.5
                extra["evidence"] = "route found (static fallback, no live crawl)"
            else:
                e = 0.0
                extra["evidence"] = f"route {matched_route} not in page inventory"

    elif etype == "element":
        matched_label = grounding.get("matched_element_label")
        match_source = grounding.get("match_source")
        extra["matched_element_label"] = matched_label
        extra["match_source"] = match_source
        extra["matched_selector"] = _lookup_selector(matched_label, page_inventory)
        if match_source == "playwright":
            e = 1.0
        elif match_source == "route_elements":
            e = 0.5
        else:
            e = 0.0

    elif etype == "edge":
        edge_kind = _classify_edge_kind(entity.get("label", ""))
        extra["edge_kind"] = edge_kind

        if edge_kind == "data":
            matched_ep = grounding.get("matched_endpoint")
            trigger = grounding.get("trigger_element_label")
            extra["matched_endpoint"] = matched_ep
            extra["trigger_element_label"] = trigger
            if matched_ep and trigger:
                e = 1.0
            elif matched_ep:
                e = 0.5
            elif trigger:
                e = 0.4
            else:
                e = 0.0

        elif edge_kind == "navigation":
            nav_target = grounding.get("matched_nav_target")
            match_source = grounding.get("match_source")
            extra["matched_nav_target"] = nav_target
            extra["match_source"] = match_source
            if match_source == "playwright_element":
                e = 1.0
            elif match_source == "navigation_graph":
                e = 0.5
            else:
                e = 0.0

        else:  # structural
            trigger = grounding.get("trigger_element_label")
            match_source = grounding.get("match_source")
            extra["trigger_element_label"] = trigger
            extra["match_source"] = match_source
            if match_source == "playwright":
                e = 1.0
            elif match_source == "route_elements":
                e = 0.5
            else:
                e = 0.0

    else:
        e = 0.0

    return e, extra


def _aggregate(entity_scores: list) -> float:
    primary = [s["e"] for s in entity_scores if s.get("primary") and s.get("e") is not None]
    secondary = [s["e"] for s in entity_scores if not s.get("primary") and s.get("e") is not None]

    if not primary and not secondary:
        return 0.0
    if primary and secondary:
        p_avg = sum(primary) / len(primary)
        s_avg = sum(secondary) / len(secondary)
        return round(0.7 * p_avg + 0.3 * s_avg, 6)
    if primary:
        return round(sum(primary) / len(primary), 6)
    return round(sum(secondary) / len(secondary), 6)


def _compute_unlinked(
    l1a_reqs: list,
    mapped: list,
    step5_pages: list,
    impl_units: list,
) -> tuple[list, list]:
    l1a_ids = {r.get("req_id") for r in l1a_reqs}

    matched_routes: set = set()
    for m in mapped:
        if m["req_id"] in l1a_ids:
            for es in m.get("entity_scores", []):
                if es.get("type") == "node" and es.get("matched_route"):
                    matched_routes.add(es["matched_route"])

    unlinked_l2 = [
        {
            "route": page.get("route", ""),
            "title": page.get("title"),
            "note": "No L1a requirement's path[] node entity matched this route",
        }
        for page in step5_pages
        if page.get("accessible") is True and page.get("route", "") not in matched_routes
    ]

    matched_endpoints: set = set()
    for m in mapped:
        if m["req_id"] in l1a_ids:
            for es in m.get("entity_scores", []):
                if es.get("type") == "edge" and es.get("edge_kind") == "data":
                    ep = es.get("matched_endpoint")
                    if ep:
                        matched_endpoints.add(ep)

    unlinked_l3 = []
    for unit in impl_units:
        if unit.get("kind") != "api_endpoint":
            continue
        method = unit.get("method") or ""
        upath = unit.get("path") or ""
        endpoint_key = f"{method} {upath}".strip()
        if endpoint_key not in matched_endpoints:
            unlinked_l3.append({
                "method": method or None,
                "path": upath or None,
                "handler": unit.get("handler"),
                "file": unit.get("file"),
                "note": "No L1a requirement matched this endpoint as its L3 signal",
            })

    return unlinked_l2, unlinked_l3


async def run(
    step3_5: dict,
    step4: dict,
    step5: dict,
    client: anthropic.AsyncAnthropic,
) -> dict:
    try:
        l1a_reqs = step3_5.get("confirmed_requirements", [])
        l1b_reqs = step3_5.get("advisory_requirements", [])
        all_reqs = l1a_reqs + l1b_reqs

        frontend_routes = step4.get("frontend_routes", [])
        impl_units = step4.get("implementation_units", [])
        route_elements = step4.get("route_elements", {})
        navigation_graph = step4.get("navigation_graph", {})
        step5_pages = step5.get("pages", [])

        page_inventory = _build_page_inventory(step5_pages, route_elements)
        nav_inventory = _build_nav_inventory(navigation_graph, step5_pages)

        grounding_lists = await asyncio.gather(
            *[
                _ground_requirement(
                    req, frontend_routes, page_inventory, nav_inventory, impl_units, client
                )
                for req in all_reqs
            ],
            return_exceptions=True,
        )

        mapped = []
        for req, grounding_list in zip(all_reqs, grounding_lists):
            path = req.get("path", [])

            if isinstance(grounding_list, Exception) or not isinstance(grounding_list, list):
                grounding_list = [{}] * len(path)
            while len(grounding_list) < len(path):
                grounding_list.append({})

            entity_scores = []
            for entity, grounding in zip(path, grounding_list):
                e, extra = _score_entity(entity, grounding, page_inventory)
                entity_scores.append({
                    "label": entity.get("label", ""),
                    "type": entity.get("type", ""),
                    "primary": entity.get("primary", True),
                    "e": e,
                    **extra,
                })

            mapped.append({
                "req_id": req.get("req_id", ""),
                "description": req.get("description", ""),
                "e_score": round(_aggregate(entity_scores), 4),
                "entity_scores": entity_scores,
            })

        unlinked_l2, unlinked_l3 = _compute_unlinked(l1a_reqs, mapped, step5_pages, impl_units)

        return {
            "mapped": mapped,
            "unlinked_l2": unlinked_l2,
            "unlinked_l3": unlinked_l3,
            "llm_model": MODEL,
            "error": None,
        }

    except Exception as exc:
        return {
            "mapped": [],
            "unlinked_l2": [],
            "unlinked_l3": [],
            "llm_model": MODEL,
            "error": str(exc),
        }
