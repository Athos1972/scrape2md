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

### URL direkt als Argument übergeben

```bash
scrape2md "https://docs.example.com/getting-started"
```

Oder Config laden und nur `start_url` überschreiben:

```bash
scrape2md "https://docs.example.com/getting-started" --config config.toml
```

Am Ende der Ausführung wird eine Zusammenfassung ausgegeben:

- Anzahl Seiten
- Anzahl Assets
- Anzahl Fehler
- Zielordner

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
