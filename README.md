# scrape2md

Kleines CLI-Beispiel, das Markdown erzeugt.
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

## Änderung
Der Output-Pfad wird aus der TOML-Config gelesen (`output_path`) statt hart im Code zu stehen.
## Nicht-Scope

## Konfiguration
Kopiere die Beispielconfig und passe den Pfad an:
- Login-Flows
- Confluence/Jira/Teams/Mail-spezifische Logik
- DB/Persistenzschicht
- OCR, Embeddings, Chunking
- direkte Einsortierung in ein Domainmodell

## Installation

```bash
cp example.toml config.toml
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Beispiel (`config.toml`):

```toml
output_path = "output/result.md"
```

## Nutzung
Optional für Entwicklung:

```bash
python3 scrape2md.py --config config.toml --title "Mein Titel" --content "Mein Inhalt"
pip install -e .[dev]
```

## Abhängigkeiten

- Python 3.12+
- `crawl4ai` (primäre Engine, mit HTTP-Fallback)
- `httpx`, `beautifulsoup4`, `markdownify`
- `typer`

## CLI-Beispiele

```bash
scrape2md --config configs/example.toml
python scripts/crawl_site.py --config configs/example.toml
```

Die Option `--config` ist verpflichtend. Ohne Angabe bricht das CLI mit einer klaren Fehlermeldung ab.
Ausgabe am Ende:
- Anzahl Seiten
- Anzahl Assets
- Anzahl Fehler
- Zielordner

## Konfiguration (TOML)

Siehe `configs/example.toml`.

Die Datei wird an den in `output_path` definierten Ort geschrieben.
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
