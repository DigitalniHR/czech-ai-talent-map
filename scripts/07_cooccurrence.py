#!/usr/bin/env python3
"""Czech AI Talent Map — data pipeline (live-aggregation, 0 LLM).

Vstup:  ../ai-market-mirror-cz/data.db (SQLite, pass populace ze S2).
Výstup: public/data.json — minimal payload pro browser-side live aggregation.

Žádné per-skill aggregates v JSONu. Frontend si počty / top firmy / top školy /
co-occurrence dopočítává live z `people_vectors[]` při každé filter change.
Tím se bubble velikosti reaktivně updatují podle aktuálního filtru.

Payload obsahuje:
- `stats`: {total_professionals, total_companies, generated_at, k_anonymity}
- `technologies[]`: per-skill metadata jen `{id, name, type, relevance}` z catalogu.
  Žádný count — frontend si dopočítá. Filtrováno `relevance != 'non_ai'`,
  posbíráno top N podle global frequency.
- `people_vectors[]`: per-osoba {skills, seniority, location, company, school}.
  Skills filtrované na top N (= co se v UI dá vybrat). Company + school s
  k-anonymity guard ≥5.

Usage:
    python3 scripts/07_cooccurrence.py
    python3 scripts/07_cooccurrence.py --db /path/to/data.db --out-dir public/
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

TOP_N_TECH = 40
K_ANON = 5


def _location_bucket(loc_text: str, country_code: str) -> str:
    if country_code and country_code.upper() != "CZ":
        return "Abroad"
    lt = (loc_text or "").lower()
    if "praha" in lt or "prague" in lt:
        return "Prague"
    if "brno" in lt:
        return "Brno"
    if "ostrava" in lt:
        return "Ostrava"
    return "Remote"


def _seniority_bucket(mm_seniority: str, total_years) -> str | None:
    """Mapování 5 DB úrovní → 5 spec úrovní (Junior/Mid/Senior/Lead/C-level)."""
    if not mm_seniority:
        return None
    if mm_seniority == "junior":
        return "Junior"
    if mm_seniority == "ic":
        if isinstance(total_years, (int, float)) and total_years < 5:
            return "Mid"
        return "Senior"
    if mm_seniority in ("lead", "architect"):
        return "Lead"
    if mm_seniority == "director_plus":
        return "C-level"
    return None


def load_catalog(catalog_path: Path) -> dict:
    with catalog_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out = {}
    for s in data.get("skills") or []:
        c = s.get("canonical")
        if c:
            out[c] = {
                "type": s.get("type", "unknown"),
                "relevance": s.get("relevance", "unknown"),
            }
    return out


def build_payload(db_path: Path, catalog: dict) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT mm_skills, mm_seniority, mm_career_metrics, mm_clean_json,
               mm_current_company, mm_current_company_li_id,
               mm_school_canonical
        FROM people
        WHERE mm_prefilter='pass' AND mm_skills IS NOT NULL
        """
    ).fetchall()
    conn.close()

    skill_freq: Counter = Counter()
    company_counts: Counter = Counter()
    school_counts: Counter = Counter()
    company_li_ids: set = set()
    per_profile: list = []

    for r in rows:
        try:
            skills = json.loads(r["mm_skills"] or "[]")
        except json.JSONDecodeError:
            skills = []

        metrics = {}
        if r["mm_career_metrics"]:
            try:
                metrics = json.loads(r["mm_career_metrics"])
            except (TypeError, json.JSONDecodeError):
                pass

        clean = {}
        if r["mm_clean_json"]:
            try:
                clean = json.loads(r["mm_clean_json"])
            except (TypeError, json.JSONDecodeError):
                pass

        location = _location_bucket(
            clean.get("location_text", ""), clean.get("country_code", "")
        )
        seniority = _seniority_bucket(r["mm_seniority"], metrics.get("total_years"))

        skills_set = set(skills)
        for s in skills_set:
            skill_freq[s] += 1
        if r["mm_current_company"]:
            company_counts[r["mm_current_company"]] += 1
        if r["mm_current_company_li_id"]:
            company_li_ids.add(r["mm_current_company_li_id"])
        if r["mm_school_canonical"]:
            school_counts[r["mm_school_canonical"]] += 1

        per_profile.append({
            "skills": skills_set,
            "seniority": seniority,
            "location": location,
            "company": r["mm_current_company"],
            "school": r["mm_school_canonical"],
        })

    # K-anon sets
    safe_companies = {c for c, n in company_counts.items() if n >= K_ANON}
    safe_schools = {s for s, n in school_counts.items() if n >= K_ANON}

    # Skill relevance sets z catalogu
    core_ai_skills = {c for c, m in catalog.items() if m.get("relevance") == "core_ai"}
    ai_relevant = core_ai_skills | {
        c for c, m in catalog.items() if m.get("relevance") == "adjacent"
    }

    # FILTR STUDIE: pass-S2 + má alespoň 1 core_ai skill.
    # Lidé bez core_ai skillu (jen non_ai / generic adjacent) do studie nepatří —
    # nejsou to AI talent.
    per_profile = [p for p in per_profile if p["skills"] & core_ai_skills]

    # Top N skills — vyfiltrovat non_ai pryč, jen core_ai + adjacent.
    # Recompute skill_freq po core_ai filtru — počty se mírně sníží.
    skill_freq = Counter()
    for p in per_profile:
        for s in p["skills"]:
            skill_freq[s] += 1

    top_techs = [
        t for t, _ in skill_freq.most_common()
        if t in ai_relevant
    ][:TOP_N_TECH]
    top_set = set(top_techs)

    # Technology metadata (žádný count — frontend si dopočítá live)
    technologies = []
    for t in top_techs:
        meta = catalog.get(t, {})
        technologies.append({
            "id": t,
            "name": t,
            "type": meta.get("type", "unknown"),
            "relevance": meta.get("relevance", "unknown"),
        })

    # People_vectors (k-anon company + school, skills filtered na top N)
    people_vectors = []
    for p in per_profile:
        relevant_skills = sorted(p["skills"] & top_set)
        people_vectors.append({
            "skills": relevant_skills,
            "seniority": p["seniority"],
            "location": p["location"],
            "company": p["company"] if p["company"] in safe_companies else None,
            "school": p["school"] if p["school"] in safe_schools else None,
        })

    # Total companies — unikátní firmy mezi lidmi v studii (po core_ai filtru)
    study_company_li_ids = set()
    for r in rows:
        try:
            sk = set(json.loads(r["mm_skills"] or "[]"))
        except json.JSONDecodeError:
            sk = set()
        if sk & core_ai_skills and r["mm_current_company_li_id"]:
            study_company_li_ids.add(r["mm_current_company_li_id"])

    return {
        "version": "v3.1-core-ai-filter",
        "stats": {
            "total_professionals": len(per_profile),
            "total_companies": len(study_company_li_ids),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "skills_in_top": len(top_techs),
            "k_anonymity": K_ANON,
            "scope": "mm_prefilter='pass' AND has ≥1 core_ai skill",
        },
        "technologies": technologies,
        "people_vectors": people_vectors,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    project_dir = Path(__file__).resolve().parent.parent
    default_db = (project_dir.parent / "ai-market-mirror-cz" / "data.db").resolve()
    default_catalog = (
        project_dir.parent / "ai-market-mirror-cz" / "pipeline" / "taxonomy"
        / "skills_catalog.yaml"
    ).resolve()
    default_out_dir = project_dir / "public"
    p.add_argument("--db", default=str(default_db))
    p.add_argument("--catalog", default=str(default_catalog))
    p.add_argument("--out-dir", default=str(default_out_dir))
    args = p.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out_dir)
    catalog_path = Path(args.catalog)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    if not catalog_path.exists():
        raise SystemExit(f"Catalog not found: {catalog_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog(catalog_path)
    payload = build_payload(db_path, catalog)
    out_path = out_dir / "data.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Smazat legacy datasety
    for legacy in ("data_engineers.json", "data_adjacent.json"):
        p_legacy = out_dir / legacy
        if p_legacy.exists():
            p_legacy.unlink()

    print(json.dumps({
        "success": True,
        "professionals": payload["stats"]["total_professionals"],
        "companies": payload["stats"]["total_companies"],
        "technologies": len(payload["technologies"]),
        "people_vectors": len(payload["people_vectors"]),
        "output": str(out_path),
        "size_kb": round(out_path.stat().st_size / 1024, 1),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
