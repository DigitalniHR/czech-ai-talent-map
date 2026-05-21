#!/usr/bin/env python3
"""Pipeline testy pro 07_cooccurrence.py.

Spustit:
    cd czech-ai-talent-map
    python3 -m pytest tests/ -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = PROJECT_DIR / "public"
DATASETS = {
    "all": PUBLIC_DIR / "data.json",
    "engineers": PUBLIC_DIR / "data_engineers.json",
    "adjacent": PUBLIC_DIR / "data_adjacent.json",
}
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

# Sanity: všechny 3 datasety existují a jsou validní (pipeline byla spuštěna)
for label, path in DATASETS.items():
    assert path.exists(), (
        f"{path.name} neexistuje — spusť `python3 scripts/07_cooccurrence.py`"
    )
PAYLOADS = {label: json.loads(p.read_text(encoding="utf-8")) for label, p in DATASETS.items()}
PAYLOAD = PAYLOADS["all"]   # backward-compat pro existující testy


# --- Schema sanity ---------------------------------------------------------

def test_top_level_keys():
    assert set(PAYLOAD.keys()) == {
        "stats", "technologies", "cooccurrence", "people_vectors",
    }


def test_stats_shape():
    s = PAYLOAD["stats"]
    assert isinstance(s["total_professionals"], int)
    assert isinstance(s["total_companies"], int)
    assert isinstance(s["generated_at"], str)
    assert s["total_professionals"] > 0
    assert s["total_companies"] > 0


def test_tech_count_is_40():
    """Spec: přesně 40 technologií."""
    assert len(PAYLOAD["technologies"]) == 40


def test_tech_schema():
    """Každá tech má povinná pole + správné typy."""
    for t in PAYLOAD["technologies"]:
        assert isinstance(t["id"], str) and t["id"]
        assert isinstance(t["count"], int) and t["count"] > 0
        assert isinstance(t["top_domain"], str)
        assert isinstance(t["domains"], dict)
        assert isinstance(t["roles"], dict)
        assert isinstance(t["companies"], list)
        assert len(t["companies"]) <= 6
        for c in t["companies"]:
            assert isinstance(c["name"], str) and c["name"]
            assert isinstance(c["count"], int) and c["count"] > 0


def test_tech_sorted_by_count():
    counts = [t["count"] for t in PAYLOAD["technologies"]]
    assert counts == sorted(counts, reverse=True), "Tech není seřazené sestupně"


def test_top_domain_in_breakdown():
    """top_domain musí být klíč v domains breakdown."""
    for t in PAYLOAD["technologies"]:
        assert t["top_domain"] in t["domains"], (
            f"{t['id']}: top_domain={t['top_domain']!r} chybí v {list(t['domains'])}"
        )


# --- Co-occurrence ---------------------------------------------------------

def test_cooccurrence_threshold():
    """Spec: minimum 15 sdílených profesionálů."""
    for c in PAYLOAD["cooccurrence"]:
        assert c["value"] >= 15, (
            f"{c['source']}↔{c['target']} value {c['value']} < 15"
        )


def test_cooccurrence_only_top_techs():
    """Co-occurrence smí obsahovat jen top 40 technologií."""
    top_ids = {t["id"] for t in PAYLOAD["technologies"]}
    for c in PAYLOAD["cooccurrence"]:
        assert c["source"] in top_ids
        assert c["target"] in top_ids


def test_cooccurrence_no_self_pairs():
    for c in PAYLOAD["cooccurrence"]:
        assert c["source"] != c["target"]


def test_cooccurrence_no_duplicate_pairs():
    """{A,B} = {B,A}, nesmí být dvojí."""
    seen = set()
    for c in PAYLOAD["cooccurrence"]:
        key = tuple(sorted((c["source"], c["target"])))
        assert key not in seen, f"Duplicate pair {key}"
        seen.add(key)


# --- People vectors (anonymity!) -------------------------------------------

def test_people_vectors_count_matches_total():
    assert len(PAYLOAD["people_vectors"]) == PAYLOAD["stats"]["total_professionals"]


def test_people_vectors_anonymized():
    """Žádný PII field — name, linkedin_url, email, company_id."""
    forbidden = {"name", "linkedin_url", "linkedinUrl", "email",
                 "company", "company_id", "id", "headline", "about"}
    for v in PAYLOAD["people_vectors"]:
        for f in forbidden:
            assert f not in v, (
                f"PII leak: pole {f!r} přítomné v people_vectors"
            )


def test_people_vectors_schema():
    valid_locations = {"Prague", "Brno", "Ostrava", "Remote", "Abroad"}
    valid_seniority = {"Junior", "Mid", "Senior", "Lead", "C-level", None}
    for v in PAYLOAD["people_vectors"]:
        assert set(v.keys()) == {"skills", "seniority", "location"}
        assert isinstance(v["skills"], list)
        assert v["location"] in valid_locations
        assert v["seniority"] in valid_seniority


def test_people_vector_skills_are_in_top_40():
    """Skills v people_vectors musí být subset top 40 — calculator nabízí jen ty."""
    top_ids = {t["id"] for t in PAYLOAD["technologies"]}
    for v in PAYLOAD["people_vectors"]:
        for s in v["skills"]:
            assert s in top_ids, f"Skill {s!r} mimo top 40"


# --- Calculator math correctness -------------------------------------------

def test_calculator_default_count():
    """Bez filtrů = total_professionals (4 468)."""
    assert len(PAYLOAD["people_vectors"]) == PAYLOAD["stats"]["total_professionals"]


def test_calculator_single_skill():
    """Skill filter má odpovídat count z technologies."""
    for tech in PAYLOAD["technologies"][:5]:
        n_from_filter = sum(
            1 for v in PAYLOAD["people_vectors"] if tech["id"] in v["skills"]
        )
        assert n_from_filter == tech["count"], (
            f"{tech['id']}: calculator filter ({n_from_filter}) != "
            f"tech count ({tech['count']})"
        )


def test_calculator_and_or_logic():
    """AND ⊆ OR pro 2 skilly."""
    skills_two = [PAYLOAD["technologies"][0]["id"],
                  PAYLOAD["technologies"][1]["id"]]
    or_count = sum(
        1 for v in PAYLOAD["people_vectors"]
        if any(s in v["skills"] for s in skills_two)
    )
    and_count = sum(
        1 for v in PAYLOAD["people_vectors"]
        if all(s in v["skills"] for s in skills_two)
    )
    assert and_count <= or_count


# --- Domain consistency ----------------------------------------------------

def test_domains_match_spec():
    """Domains v breakdown musí být ze spec barvové sady."""
    spec_domains = {
        "NLP / LLM", "Computer Vision", "Generative AI",
        "Classic ML", "Robotics", "General",
    }
    for t in PAYLOAD["technologies"]:
        for d in t["domains"]:
            assert d in spec_domains, f"Neznámá doména {d!r} u {t['id']}"


# --- Multi-dataset tests (3 populace) -------------------------------------

def test_all_datasets_have_required_shape():
    for label, payload in PAYLOADS.items():
        assert set(payload.keys()) == {"stats", "technologies", "cooccurrence", "people_vectors"}, label
        assert payload["stats"]["dataset_label"] == label
        assert isinstance(payload["stats"]["segments"], list)
        assert payload["stats"]["total_professionals"] > 0


def test_dataset_populations_correct():
    """Engineers = core_aiml + data, Adjacent = jen adjacent, All = vše."""
    assert PAYLOADS["all"]["stats"]["segments"] == ["core_aiml", "data", "adjacent"]
    assert PAYLOADS["engineers"]["stats"]["segments"] == ["core_aiml", "data"]
    assert PAYLOADS["adjacent"]["stats"]["segments"] == ["adjacent"]


def test_engineers_subset_of_all():
    """Engineers populace musí být menší než All (subset segmentů)."""
    assert PAYLOADS["engineers"]["stats"]["total_professionals"] < PAYLOADS["all"]["stats"]["total_professionals"]
    assert PAYLOADS["adjacent"]["stats"]["total_professionals"] < PAYLOADS["all"]["stats"]["total_professionals"]


def test_engineers_plus_adjacent_equals_all():
    """Engineers (core+data) + Adjacent (adjacent) = All."""
    eng = PAYLOADS["engineers"]["stats"]["total_professionals"]
    adj = PAYLOADS["adjacent"]["stats"]["total_professionals"]
    total = PAYLOADS["all"]["stats"]["total_professionals"]
    assert eng + adj == total, f"{eng} + {adj} != {total}"


def test_skill_category_field_present():
    """Každá tech má category ∈ {core, adjacent} pro frontend skill scope toggle."""
    for label, payload in PAYLOADS.items():
        for t in payload["technologies"]:
            assert t.get("category") in {"core", "adjacent"}, (
                f"{label}/{t['id']}: invalid category {t.get('category')!r}"
            )


def test_core_only_filter_produces_results():
    """Filtr „core only" v každém datasetu vrátí ≥5 technologií (jinak nepoužitelné)."""
    for label, payload in PAYLOADS.items():
        core_techs = [t for t in payload["technologies"] if t["category"] == "core"]
        assert len(core_techs) >= 5, f"{label}: jen {len(core_techs)} core technologií"


if __name__ == "__main__":
    # Standalone bez pytest
    import inspect
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed.append(fn.__name__)
    print()
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
