def _is_state_variant(label: str) -> bool:
    return "(" in label and label.rstrip().endswith(")")


def _extract_nodes_from_paths(requirements: list) -> list[str]:
    seen: dict[str, bool] = {}
    for func in requirements:
        for entity in func.get("path", []):
            if entity.get("type") == "node":
                label = str(entity.get("label", "")).strip()
                if label and not _is_state_variant(label) and label not in seen:
                    seen[label] = True
    return list(seen.keys())


def _identify_root_node(step1_requirements: list, discovered_pages: list) -> str | None:
    unique_nodes = _extract_nodes_from_paths(step1_requirements)

    if len(unique_nodes) == 1:
        return unique_nodes[0]

    is_single_file_spa = (
        len(discovered_pages) == 1
        and any(p.lower() in ("index.html", "index.htm") for p in discovered_pages)
    )
    if is_single_file_spa and unique_nodes:
        return unique_nodes[0]

    home_names = {"home", "landing", "index", "main", "dashboard", "root"}
    for func in step1_requirements:
        if func.get("priority") == "critical":
            for entity in func.get("path", []):
                if entity.get("type") == "node" and entity.get("primary"):
                    label = str(entity.get("label", ""))
                    if any(h in label.lower() for h in home_names):
                        return label

    return None


def _validate_path(path) -> list | None:
    if not isinstance(path, list) or len(path) == 0:
        return None
    clean = []
    for entity in path:
        if not isinstance(entity, dict):
            continue
        if entity.get("type") not in {"node", "element", "edge"}:
            continue
        if not str(entity.get("label", "")).strip():
            continue
        entity.setdefault("primary", True)
        clean.append(entity)
    return clean if clean else None
