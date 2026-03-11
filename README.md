# scrape2md

Kleines CLI-Beispiel, das Markdown erzeugt.

## Änderung
Der Output-Pfad wird aus der TOML-Config gelesen (`output_path`) statt hart im Code zu stehen.

## Konfiguration
Kopiere die Beispielconfig und passe den Pfad an:

```bash
cp example.toml config.toml
```

Beispiel (`config.toml`):

```toml
output_path = "output/result.md"
```

## Nutzung

```bash
python3 scrape2md.py --config config.toml --title "Mein Titel" --content "Mein Inhalt"
```

Die Datei wird an den in `output_path` definierten Ort geschrieben.
