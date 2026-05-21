---
created: 21-09-2026T20:09
updated: 21-09-2026T20:09
---
# Czech AI Talent Map

Statická vizualizační aplikace nad daty z [AI Market Mirror CZ](../ai-market-mirror-cz/) pipeline. Hostuje se na Railway jako static site, embeduje se přes iframe na `digitalnihr.cz/ai-talent-mapa`.

**Dvě obrazovky v jednom HTML:**
- **Talent Map** — 40 nejpoužívanějších technologií jako fyzikální bubliny (D3 force simulation). Velikost = počet profesionálů, barva = top AI doména. Klik na bublinu → constellation mode (vybraná tech v centru, ostatní obíhají dle co-occurrence v reálné cohortě).
- **Talent Calculator** — interaktivní filtr (skills + seniority + location) s realtime počítadlem matched profesionálů. Bez backendu — JavaScript filtruje anonymizované `people_vectors` v prohlížeči.

**Toggle filtry v hlavičce:**
- **Populace:** Všichni / AI inženýři (core_aiml + data) / Adjacent role (produktové, výzkumné) — přepíná datasety
- **Zobrazit:** Vše / Jen AI — filtruje na core_ai skills (skryje Python, Docker, SQL atd.)

**Skill taxonomie:** vychází z [ESCO](https://esco.ec.europa.eu/) (Evropská komise) — viz [docs/skills-methodology.md](../ai-market-mirror-cz/docs/skills-methodology.md). 253 canonical názvů ve 3 vrstvách (core_ai / adjacent / non_ai), normalizace přes aliasy (K8s/k8s/kubernetes → Kubernetes 1×).

## Architektura

```
data.db (SQLite, lokálně v ai-market-mirror-cz/)
   ↓
scripts/07_cooccurrence.py   (spouští se lokálně 1× měsíčně)
   ↓
public/data.json             ← celá study population (4 468 lidí, default)
public/data_engineers.json   ← jen AI engineers (core_aiml + data = 2 757)
public/data_adjacent.json    ← jen adjacent role (1 711)
   ↓
public/index.html            (D3.js, žádný build step, toggle mezi datasety)
   ↓
Railway (static site)
   ↓
iframe embed na digitalnihr.cz/ai-talent-mapa
```

Čistě statická aplikace. Žádný backend, žádný server-side kód, žádný přístup k DB z prohlížeče. Data se exportují lokálně před deployem.

## Datové rozhodnutí oproti dev spec v2.0

Spec původně předpokládala `mm_tech_stack` (LLM-generovaný, max 15 položek per profil, bez normalizace). Aktuálně používáme **`mm_skills_core` + `mm_skills_adjacent`** ze Stanice 4b (deterministická extrakce přes kuratovaný 3-vrstvý katalog, žádný cap, K8s/k8s/kubernetes → Kubernetes 1×). Důvod: kvalita dat pro publikovanou studii.

Mapování domén (AI Market Mirror → spec):
- `nlp_llm` → **NLP / LLM**
- `computer_vision` → **Computer Vision**
- `genai` → **Generative AI**
- `classic_ml` → **Classic ML**
- `robotics` → **Robotics**
- `other` → **General**

Seniority bucketování (`mm_seniority` → spec):
- `junior` → Junior
- `ic` + total_years < 5 → Mid
- `ic` + total_years ≥ 5 → Senior
- `lead` + `architect` → Lead
- `director_plus` → C-level

Location (`location_text` + `country_code` → 5 buckets):
- `country_code != CZ` → Abroad
- contains "praha"/"prague" → Prague
- contains "brno" → Brno
- contains "ostrava" → Ostrava
- jinak (CZ ale ne velké tři města) → Remote

## Lokální setup

```bash
# 1. Vygenerovat data.json z DB
python3 scripts/07_cooccurrence.py

# 2. Otestovat
python3 tests/test_pipeline.py
# nebo: python3 -m pytest tests/ -v

# 3. Spustit lokálně (jakýkoli static server)
cd public
python3 -m http.server 8080
# otevři http://localhost:8080
```

## Měsíční update workflow

```bash
# 1. Aktualizovat AI Market Mirror data.db (separátní pipeline)
# 2. Re-export pro frontend
python3 scripts/07_cooccurrence.py

# 3. Test
python3 tests/test_pipeline.py

# 4. Commit & push
git add public/data.json
git commit -m "data: monthly update $(date +%Y-%m)"
git push origin main
# Railway auto-deploy ~30s
```

## Railway setup

1. Vytvořit projekt na [railway.app](https://railway.app) → "Deploy from GitHub repo"
2. Service settings:
   - Service type: **Static**
   - Root directory: `public`
   - Build / Start command: prázdné
3. Custom headers (Settings → Custom Headers) pro iframe embed v Macaly:
   ```
   X-Frame-Options: ALLOWALL
   Content-Security-Policy: frame-ancestors *
   ```
4. (Volitelné) Custom domain — Settings → Domains → např. `mapa.aimarketmirror.cz`

## Macaly embed

```html
<iframe
  src="https://czech-ai-talent-map.up.railway.app"
  width="100%"
  height="720px"
  style="border:none;border-radius:8px;display:block;"
  loading="lazy"
  title="Czech AI Talent Map">
</iframe>
```

## Struktura repa

```
czech-ai-talent-map/
├── public/
│   ├── index.html         ← celá aplikace (HTML + CSS + D3)
│   └── data.json          ← export z pipeline (commitnutý)
├── scripts/
│   └── 07_cooccurrence.py ← data export z data.db
├── tests/
│   └── test_pipeline.py   ← 18 pytest testů (schema, anonymita, math)
└── README.md
```

## Otevřené otázky pro před prvním deployment

- **CTA URL** — aktuálně `mailto:matej@aplayerz.io`. Změnit na formulář / Calendly.
- **Custom domain** — Railway subdoména stačí, nebo `mapa.aimarketmirror.cz`?
- **Repozitář veřejný / privátní** — bonus showcase vs. kontrola distribuce.
- **Analytics** — Plausible / Umami tracking? (Privacy-friendly, žádné cookies.)

Pipeline a frontend jsou produkční, otestované. Před deploymentem doplnit výše.
