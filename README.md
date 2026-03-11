# scrape2md

`scrape2md` ist ein kleines Python-CLI-Tool, das **externe Websites** crawlt und in eine lokale, stabile Exportstruktur überführt.

Ziel ist bewusst eine dünne Orchestrierungs-/Export-Schicht:
- Website-Inhalte erfassen
- HTML + Markdown speichern
- Attachments herunterladen
- Manifest mit Metadaten erzeugen

## Scope (V1)

- Start-URL crawlen
- auf erlaubte Domains begrenzen
- Seiten als HTML + Markdown exportieren
- referenzierte Binärdateien (Attachments) laden
- `manifest.json` mit Seiten/Assets/Fehlern schreiben
- robustes Logging und Fehlerisolierung (eine defekte Seite stoppt nicht den ganzen Lauf)

## Nicht-Scope

- Login-Flows
- Confluence/Jira/Teams/Mail-spezifische Logik
- DB/Persistenzschicht
- OCR, Embeddings, Chunking
- direkte Einsortierung in ein Domainmodell

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional für Entwicklung:

```bash
pip install -e .[dev]
```

## Abhängigkeiten

- Python 3.12+
- `crawl4ai` (primäre Engine, mit HTTP-Fallback)
- `httpx`, `beautifulsoup4`, `markdownify`
- `typer`

## CLI-Beispiele

```bash
scrape2md https://example.com/docs
scrape2md crawl https://example.com/docs
scrape2md --config configs/example.toml
python scripts/crawl_site.py --config configs/example.toml
```

Ausgabe am Ende:
- Anzahl Seiten
- Anzahl Assets
- Anzahl Fehler
- Zielordner

## Konfiguration (TOML)

Siehe `configs/example.toml`.

Wichtige Felder:
- `start_url`
- `output_root`
- `allowed_domains`
- `include_patterns` / `exclude_patterns`
- `max_pages`, `max_depth`
- `download_attachments`, `attachment_extensions`
- `request_timeout`, `rate_limit_seconds`
- `save_html`, `save_markdown`
- `user_agent`

## Exportstruktur

```text
exports/<domain>/
  html/
  pages/
  assets/
  manifest.json
```

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
