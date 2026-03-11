# scrape2md

Kleines CLI-Beispiel, das Markdown erzeugt.

## Änderung
Der `output`-Pfad wird jetzt aus der Config gelesen (`output_path`) statt hart im Code zu stehen.

## Konfiguration
Kopiere die Beispielconfig und passe den Pfad an:

```bash
cp config.example.json config.json
```

Beispiel (`config.json`):

```json
{
  "output_path": "output/result.md"
}
```

## Nutzung

```bash
python3 scrape2md.py --config config.json --title "Mein Titel" --content "Mein Inhalt"
```

Die Datei wird an den in `output_path` definierten Ort geschrieben.
