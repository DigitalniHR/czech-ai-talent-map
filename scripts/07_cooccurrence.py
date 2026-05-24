#!/usr/bin/env python3
"""Czech AI Talent Map — data pipeline.

Vstup:  ../ai-market-mirror-cz/data.db (SQLite, kvalifikovaná populace).
Výstup: public/data.json (statický payload pro D3 frontend).

Jeden běh ~1 s na 4 468 lidech. Spouští se lokálně 1× měsíčně po update DB.

Klíčová rozhodnutí oproti dev spec v2.0:
- Skill source = `mm_skills_core` + `mm_skills_adjacent` (deterministická
  Stanice 4b, kuratovaný katalog, žádný cap), NE legacy `mm_tech_stack`.
- Seniority mapping: junior→Junior, ic+<5y→Mid, ic+≥5y→Senior, lead/architect
  →Lead, director_plus→C-level.
- Location: Prague (Praha), Brno, Ostrava, Abroad (country!=CZ), Remote (jiné CZ).
- AI domain → spec barvy: nlp_llm→NLP/LLM, computer_vision→Computer Vision,
  genai→Generative AI, classic_ml→Classic ML, robotics→Robotics, other→General.

Pipeline generuje 3 datasety podle vybrané populace (toggle ve frontendu):
- data.json (default) — celá study population (core_aiml + data + adjacent)
- data_engineers.json — jen core_aiml + data (skuteční AI/ML engineers)
- data_adjacent.json — jen segment adjacent (produktoví, výzkumní, AI-aware)

Každý dataset má vlastní top 40, co-occurrence matrix a people_vectors.
Skill kategorie (core_ai / adjacent) je v `technologies[].category` pro
frontend toggle „Jen core skills" / „Core + adjacent".

Usage:
    python3 scripts/07_cooccurrence.py
    python3 scripts/07_cooccurrence.py --db /path/to/data.db --out-dir public/
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

STUDY_SEGMENTS = ("core_aiml", "data", "adjacent")
TOP_N_TECH = 40
COOCCURRENCE_THRESHOLD = 15
TOP_COMPANIES_PER_TECH = 6
# k-anonymity threshold: firma se v per-person vektoru objeví jen tehdy,
# když má v datasetu alespoň tolik lidí. Chrání před deanonymizací malých firem
# kombinací (skills + seniority + location + company). Role se nefiltruje —
# kanonický enum (ml_engineer, data_scientist…) má z definice širokou populaci.
COMPANY_ANON_K = 5

DOMAIN_LABEL = {
    "nlp_llm": "NLP / LLM",
    "computer_vision": "Computer Vision",
    "genai": "Generative AI",
    "classic_ml": "Classic ML",
    "robotics": "Robotics",
    "other": "General",
}

ROLE_LABEL = {
    "ml_engineer": "ML Engineer",
    "research_scientist": "Research Scientist",
    "data_scientist": "Data Scientist",
    "data_engineer": "Data Engineer",
    "mlops_engineer": "MLOps Engineer",
    "ai_product": "AI Product",
    "software_engineer": "Software Engineer",
    "manager": "Manager",
    "other": "Other",
}


def _location_bucket(loc_text: str, country_code: str) -> str:
    """Pětibucketové mapování pro Calculator filter."""
    if country_code and country_code.upper() != "CZ":
        return "Abroad"
    lt = (loc_text or "").lower()
    if "praha" in lt or "prague" in lt:
        return "Prague"
    if "brno" in lt:
        return "Brno"
    if "ostrava" in lt:
        return "Ostrava"
    return "Remote"   # CZ profil mimo velkých 3 měst — bucket „Remote" per spec


def _seniority_bucket(mm_seniority: str, total_years) -> str | None:
    """Mapování 5 DB úrovní → 5 spec úrovní (Junior/Mid/Senior/Lead/C-level)."""
    if not mm_seniority:
        return None
    if mm_seniority == "junior":
        return "Junior"
    if mm_seniority == "ic":
        # IC = individual contributor, split podle let praxe
        if isinstance(total_years, (int, float)) and total_years < 5:
            return "Mid"
        return "Senior"
    if mm_seniority in ("lead", "architect"):
        return "Lead"
    if mm_seniority == "director_plus":
        return "C-level"
    return None


def _profile_skills(core_json, adj_json) -> tuple:
    """Vrací (all_skills_list, category_map={skill: 'core'|'adjacent'})."""
    skills = []
    category = {}
    for raw, cat in ((core_json, "core"), (adj_json, "adjacent")):
        if not raw:
            continue
        try:
            for s in json.loads(raw):
                skills.append(s)
                category[s] = cat
        except (TypeError, json.JSONDecodeError):
            continue
    return skills, category


def build_payload(db_path: Path, segments: tuple) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(segments))
    rows = conn.execute(
        f"SELECT id, mm_segment, mm_seniority, mm_role, mm_ai_domain, "
        f"mm_current_company, mm_career_metrics, mm_clean_json, "
        f"mm_skills_core, mm_skills_adjacent FROM people "
        f"WHERE mm_segment IN ({placeholders})",
        segments,
    ).fetchall()
    conn.close()

    # Pass 1: skill frequency napříč populací (pro výběr top 40)
    skill_freq: Counter = Counter()
    skill_category: dict = {}        # canonical → 'core' | 'adjacent'
    per_profile_skills: list = []   # [(skills_set, dom, role, company, location, seniority)]
    for r in rows:
        skills, profile_categories = _profile_skills(r["mm_skills_core"], r["mm_skills_adjacent"])
        skill_category.update(profile_categories)
        if not skills:
            # Profil bez skillů — do calculator pojde s prázdným listem, ale
            # do co-occurrence/top-tech nepřispěje. Stejně přidám pro celkový count.
            pass
        skills_set = set(skills)
        for s in skills_set:
            skill_freq[s] += 1

        metrics = {}
        if r["mm_career_metrics"]:
            try:
                metrics = json.loads(r["mm_career_metrics"])
            except (TypeError, json.JSONDecodeError):
                metrics = {}
        total_years = metrics.get("total_years")

        clean = {}
        if r["mm_clean_json"]:
            try:
                clean = json.loads(r["mm_clean_json"])
            except (TypeError, json.JSONDecodeError):
                clean = {}
        location = _location_bucket(
            clean.get("location_text", ""), clean.get("country_code", "")
        )
        seniority = _seniority_bucket(r["mm_seniority"], total_years)

        per_profile_skills.append({
            "skills": skills_set,
            "skills_list": skills,   # zachovat pořadí pro people_vectors
            "domain": r["mm_ai_domain"] or "other",
            "role": r["mm_role"],
            "company": r["mm_current_company"],
            "location": location,
            "seniority": seniority,
        })

    top_techs = [t for t, _ in skill_freq.most_common(TOP_N_TECH)]
    top_set = set(top_techs)

    # Pass 2: pro každou top tech agregovat domain/role/companies breakdown
    tech_aggregates = {}
    for tech in top_techs:
        tech_aggregates[tech] = {
            "id": tech,
            "count": skill_freq[tech],
            "domains_raw": Counter(),
            "roles_raw": Counter(),
            "companies_raw": Counter(),
        }

    for p in per_profile_skills:
        for tech in p["skills"]:
            if tech not in tech_aggregates:
                continue
            tech_aggregates[tech]["domains_raw"][p["domain"]] += 1
            if p["role"]:
                tech_aggregates[tech]["roles_raw"][p["role"]] += 1
            if p["company"]:
                tech_aggregates[tech]["companies_raw"][p["company"]] += 1

    technologies = []
    for tech, agg in tech_aggregates.items():
        domains = {DOMAIN_LABEL.get(k, k): v for k, v in agg["domains_raw"].items()}
        top_domain_raw = (
            agg["domains_raw"].most_common(1)[0][0]
            if agg["domains_raw"] else "other"
        )
        roles = {
            ROLE_LABEL.get(k, k): v
            for k, v in agg["roles_raw"].most_common(8)
        }
        companies = [
            {"name": c, "count": n}
            for c, n in agg["companies_raw"].most_common(TOP_COMPANIES_PER_TECH)
        ]
        technologies.append({
            "id": tech,
            "category": skill_category.get(tech, "adjacent"),  # core | adjacent
            "count": agg["count"],
            "top_domain": DOMAIN_LABEL.get(top_domain_raw, top_domain_raw),
            "domains": domains,
            "roles": roles,
            "companies": companies,
        })

    # Pass 3: co-occurrence matrix (top 40 × top 40, threshold 15)
    pair_freq: Counter = Counter()
    for p in per_profile_skills:
        relevant = sorted(p["skills"] & top_set)
        for i, a in enumerate(relevant):
            for b in relevant[i + 1:]:
                pair_freq[(a, b)] += 1

    cooccurrence = [
        {"source": a, "target": b, "value": v}
        for (a, b), v in pair_freq.items()
        if v >= COOCCURRENCE_THRESHOLD
    ]
    cooccurrence.sort(key=lambda x: -x["value"])

    # Pass 4a: spočítat safe_companies (k-anonymity guard) — firmy s >= K lidi
    # v datasetu, aby se nedaly deanonymizovat kombinací filtrů v Calculatoru.
    company_counts: Counter = Counter()
    for p in per_profile_skills:
        if p["company"]:
            company_counts[p["company"]] += 1
    safe_companies = {c for c, n in company_counts.items() if n >= COMPANY_ANON_K}

    # Pass 4b: people_vectors (anonymized) pro Talent Calculator
    people_vectors = []
    for p in per_profile_skills:
        # Filter skills na top 40 — calculator pracuje jen s nimi (filtry jsou
        # nabízené z top 40, nic jiného uživatel nevybere)
        relevant_skills = sorted(p["skills"] & top_set)
        vec = {
            "skills": relevant_skills,
            "seniority": p["seniority"],
            "location": p["location"],
            "role": p["role"] or None,
            "company": p["company"] if p["company"] in safe_companies else None,
        }
        people_vectors.append(vec)

    # Total companies — unique current companies napříč qualified population
    unique_companies = len({
        p["company"] for p in per_profile_skills if p["company"]
    })

    return {
        "stats": {
            "total_professionals": len(per_profile_skills),
            "total_companies": unique_companies,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "skills_in_top": len(top_techs),
            "cooccurrence_threshold": COOCCURRENCE_THRESHOLD,
        },
        "technologies": technologies,
        "cooccurrence": cooccurrence,
        "people_vectors": people_vectors,
    }


DATASETS = [
    # (filename, label, segments)
    ("data.json",          "all",       ("core_aiml", "data", "adjacent")),
    ("data_engineers.json", "engineers", ("core_aiml", "data")),
    ("data_adjacent.json",  "adjacent",  ("adjacent",)),
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    project_dir = Path(__file__).resolve().parent.parent
    default_db = (project_dir.parent / "ai-market-mirror-cz" / "data.db").resolve()
    default_out_dir = project_dir / "public"
    p.add_argument("--db", default=str(default_db), help="path to data.db")
    p.add_argument("--out-dir", default=str(default_out_dir),
                   help="adresář kam se zapíšou všechny 3 datasety")
    args = p.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out_dir)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    report = []
    for filename, label, segments in DATASETS:
        payload = build_payload(db_path, segments)
        payload["stats"]["dataset_label"] = label
        payload["stats"]["segments"] = list(segments)
        out_path = out_dir / filename
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report.append({
            "dataset": label,
            "professionals": payload["stats"]["total_professionals"],
            "companies": payload["stats"]["total_companies"],
            "technologies": len(payload["technologies"]),
            "cooccurrence_pairs": len(payload["cooccurrence"]),
            "people_vectors": len(payload["people_vectors"]),
            "output": str(out_path),
            "size_kb": round(out_path.stat().st_size / 1024, 1),
        })

    print(json.dumps({"success": True, "datasets": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
