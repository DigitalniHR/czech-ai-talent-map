---
created: 25-42-2026T12:42
updated: 25-42-2026T12:42
---
# Macaly deploy — nativně, `digitalnihr.cz/ai-talent-mapa`

**Žádný iframe.** Celý frontend žije v Macaly stránce, data se fetchnou z Railway.

Z Test 3 (2026-05-25) víme, že Macaly povolí:
- ✅ Inline `<script>` execution
- ✅ DOM mutace po renderu
- ✅ External CDN load (D3 z `cdn.jsdelivr.net`)
- ✅ `fetch()` z `czech-ai-talent-map-production.up.railway.app` (CORS ok)

Tj. vložíme **celý self-contained `<!DOCTYPE html>` blok** do Macaly stránky jako custom HTML.

## Co nahrát do Macaly

📄 **Soubor:** `MACALY_PAGE_CONTENT.html` (56 KB, 1419 řádků) — sourozenec tohoto MD.
- Obsahuje vše: `<head>` (meta + SEO + JSON-LD), `<style>` (CSS), `<body>` (HTML), `<script>` (JS s aggregací).
- Data se fetchnou z Railway: `https://czech-ai-talent-map-production.up.railway.app/data.json` (CORS `*`).

## Prompt do DHR Macaly chatu

> *„Vytvoř novou stránku na URL `/ai-talent-mapa`.*
>
> *Nastavení stránky:*
> - *Bez DHR navigation / header / footer — appka má vlastní headery a vyplní celé okno.*
> - *Title: 'Mapa českého AI talentu — interaktivní přehled 4 001 odborníků | DigitálníHR'*
> - *Meta description: 'Interaktivní mapa 4 001 AI a ML profesionálů v České republice. Top 40 technologií, AI specializace, kalkulačka dostupného talentu.'*
> - *Canonical URL: `https://www.digitalnihr.cz/ai-talent-mapa`*
> - *OG image: použij placeholder, doplníme později*
>
> *Obsah stránky = celý obsah souboru `MACALY_PAGE_CONTENT.html`, který nahraju v dalším kroku.*
>
> *Macaly nesmí sanitizovat `<script>` tagy, nesmí přepisovat CSS proměnné v `<style>` a nesmí touchnout `fetch()` URLs ven na cdn.jsdelivr.net a czech-ai-talent-map-production.up.railway.app — to už máme ověřené přes Test 3."*

Po prvním promptu nahraj soubor `MACALY_PAGE_CONTENT.html` jako attachment / asset
do toho samého chatu.

## Verifikace po deploy

Otevři `https://www.digitalnihr.cz/ai-talent-mapa` (hard refresh Cmd+Shift+R):

- [ ] HTTP 200, ne 404
- [ ] Header: brand `Mapa českého AI talentu` + KPI `4 001 profesionálů · 1 570 firem`
- [ ] Toggle `ZOBRAZIT: Vše / Jen AI` funguje
- [ ] Bubble chart 40 bublin (tyrkysové = core_ai, fialové = adjacent)
- [ ] Klik na bublinu → detail panel (Seniorita / Top firmy / Top školy / Často kombinováno s)
- [ ] Kalkulačka filter → counter + bubble velikosti se přepočítají live
- [ ] Mobile (iPhone): jen Kalkulačka tab, žádný bubble
- [ ] DevTools Network: `data.json` fetch z Railway → HTTP 200, žádné CORS errory v Console

## Jak data updatovat dál

Frontend (HTML) je teď v Macaly. Data jsou na Railway. Refresh:

1. Pipeline lokálně přegeneruje `public/data.json` (z měsíčního scrape)
2. Push do `DigitalniHR/czech-ai-talent-map` → Railway auto-redeploy ~50 s
3. Frontend v Macaly automaticky stáhne nový JSON (cache 1 h, ale `?s=<schema_version>` query param vynutí miss když schema změníš)

Frontend update (kosmetika, copy, layout): edit `public/index.html` lokálně →
zkopíruj znova celý obsah do Macaly stránky. Macaly drží jen jednu verzi
HTML obsahu.

## Otevřené otázky

- **CTA `Domluvit konzultaci`** — dnes skryté (`display: none`). Až bude jasný cíl (Calendly / formulář / mailto), v `index.html` odkomentuj.
- **GA tracking** — Talent Map nemá vlastní events. Pokud chceš trackovat klik na bublinu / filter changes, přidat `gtag('event', ...)` calls.
- **OG image** — `og-image.png` referencován v meta, ale placeholder. Vyrobit reálný (screenshot bubble chart 1200×630).
