def _compute_score(reqs: list, e_lookup: dict) -> tuple[float, dict]:
    numerator = 0.0
    denominator = 0.0

    for r in reqs:
        req_id = r.get("req_id", "")
        e = float(e_lookup.get(req_id, 0.0))
        w = float(r.get("weight", 2.0))
        numerator += e * w
        denominator += w

    score = numerator / denominator if denominator > 0.0 else 0.0
    return score, {
        "numerator": round(numerator, 4),
        "denominator": round(denominator, 4),
        "requirement_count": len(reqs),
    }


def run(step6: dict, step3_5: dict) -> dict:
    try:
        e_lookup = {
            m["req_id"]: float(m.get("e_score", 0.0))
            for m in step6.get("mapped", [])
            if "req_id" in m
        }
        l1a_reqs = step3_5.get("confirmed_requirements", [])
        l1b_reqs = step3_5.get("advisory_requirements", [])

        fcom, fcom_detail = _compute_score(l1a_reqs, e_lookup)
        fa, fa_detail = _compute_score(l1b_reqs, e_lookup)

        missing_l1a = sorted(
            [
                {
                    "req_id": r["req_id"],
                    "description": r.get("description", ""),
                    "e_score": e_lookup.get(r.get("req_id", ""), 0.0),
                    "weight": float(r.get("weight", 2.0)),
                }
                for r in l1a_reqs
                if e_lookup.get(r.get("req_id", ""), 0.0) < 0.5
            ],
            key=lambda x: x["e_score"],
        )

        missing_l1b = [
            {
                "req_id": r["req_id"],
                "description": r.get("description", ""),
                "e_score": e_lookup.get(r.get("req_id", ""), 0.0),
                "weight": float(r.get("weight", 2.0)),
                "strength": r.get("strength"),
            }
            for r in l1b_reqs
            if e_lookup.get(r.get("req_id", ""), 0.0) < 0.5
        ]

        return {
            "fcom": round(fcom, 4),
            "fa": round(fa, 4),
            "fcom_detail": fcom_detail,
            "fa_detail": fa_detail,
            "fcom_advisory": {
                "missing_l1a": missing_l1a,
                "unlinked_routes": step6.get("unlinked_l2", []),
                "unlinked_endpoints": step6.get("unlinked_l3", []),
            },
            "fa_advisory": {
                "missing_l1b": missing_l1b,
            },
            "error": None,
        }

    except Exception as exc:
        return {
            "fcom": 0.0,
            "fa": 0.0,
            "fcom_detail": {"numerator": 0.0, "denominator": 0.0, "requirement_count": 0},
            "fa_detail": {"numerator": 0.0, "denominator": 0.0, "requirement_count": 0},
            "fcom_advisory": {
                "missing_l1a": [],
                "unlinked_routes": [],
                "unlinked_endpoints": [],
            },
            "fa_advisory": {"missing_l1b": []},
            "error": str(exc),
        }
