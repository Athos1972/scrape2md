# scrape2md

`scrape2md` ist ein Python-CLI-Tool, das **externe Websites** crawlt und in eine lokale, stabile Exportstruktur schreibt.

## Scope (V1)

- Start-URL crawlen
- auf erlaubte Domains begrenzen
- Seiten als HTML + Markdown exportieren
- referenzierte Binärdateien (Attachments) herunterladen
- `manifest.json` mit Seiten/Assets/Fehlern schreiben
- robustes Logging und Fehlerisolierung (eine defekte Seite stoppt nicht den ganzen Lauf)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Für Tests/Entwicklung:

```bash
pip install -e .[dev]
```

## Konfiguration (TOML)

Nutze die Beispielkonfiguration als Vorlage:

```bash
cp configs/example.toml config.toml
```

Wichtige Felder in `config.toml`:

- `start_url`
- `output_root`
- `allowed_domains`
- `include_patterns` / `exclude_patterns`
- `max_pages`, `max_depth`
- `download_attachments`, `attachment_extensions`
- `request_timeout`, `rate_limit_seconds`
- `save_html`, `save_markdown`
- `user_agent`
- Basis: `render_js`, `wait_for_selector`, `wait_time_ms`, `wait_until`
- Dynamisch/modern: `dynamic_mode`, `scan_full_page`, `scroll_delay`, `delay_before_return_html`, `remove_consent_popups`, `remove_overlay_elements`, `process_iframes`, `flatten_shadow_dom`, `enable_menu_clicks`, `wait_for`, `js_code_before_wait`, `js_code`
- Debug: `debug_mode`, `debug_save_screenshot`

> Hinweis: Für das eigentliche Crawl-CLI gibt es **kein** `output_path`-Feld. Dieses Feld gehört nur zum separaten Demo-Skript `scrape2md.py`.

## Nutzung

### Empfohlener Aufruf (mit Config)

```bash
scrape2md --config config.toml
```

Alternativ mit dem Python-Entrypoint:

```bash
python scripts/crawl_site.py --config config.toml
```

## Dynamische Websites / Discovery-Strategie

Die Link-Discovery läuft mehrstufig:

1. Interne Links aus `CrawlResult.links` (crawl4ai payload)
2. Fallback: zusätzliche Extraktion von `a[href]` im finalen HTML
3. URL-Normalisierung + Domain-/Pattern-Filter + Duplikatentfernung
4. Trennung in Seitenlinks vs. Attachments

Bei 0 Links auf der Root-Seite wird zusätzlich `robots.txt` + `sitemap.xml` (inkl. `sitemapindex`) ausgewertet.

## Troubleshooting

### Root-Seite lädt, aber keine Links gefunden

- `dynamic_mode = true` aktivieren
- `wait_for` auf eine realistische Link-Anzahl setzen
- `enable_menu_clicks = true` lassen (öffnet generisch Menüs / aria-expanded / details)
- Logs prüfen: `result.links internal count`, `html fallback href count`, `after filtering count`

### Cookie-Banner blockiert DOM

- `remove_consent_popups = true`
- `remove_overlay_elements = true`

### Navigation liegt in Shadow DOM oder iFrame

- `process_iframes = true`
- `flatten_shadow_dom = true`

### Sitemap enthält keine brauchbaren HTML-URLs

- Ist nur Fallback/Zusatzquelle.
- Discovery erfolgt primär auf gerendertem DOM + crawl4ai links payload.

## Exportstruktur

Beispiel:

```text
exports/docs.example.com/
  html/getting-started.html
  pages/getting-started.md
  assets/manual.pdf
  manifest.json
```

## Architekturhinweis

Das Repo erzeugt **quellenneutrale Exporte**. Die spätere Einsortierung in ein Wissens-/Domainmodell erfolgt bewusst separat in einem nachgelagerten Import-/Transfer-Schritt.

## Nicht-Scope

- Login-Flows
- Confluence/Jira/Teams/Mail-spezifische Logik
- DB/Persistenzschicht
- OCR, Embeddings, Chunking
- direkte Einsortierung in ein Domainmodell
