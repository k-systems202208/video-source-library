from pathlib import Path

path = Path("windows-installer/src/library_service.py")
text = path.read_text(encoding="utf-8")
text = text.replace('f"/tmdb-image/poster/{int(r["id"])}"', 'f\'/tmdb-image/poster/{int(r["id"])}\'')
text = text.replace('f"/tmdb-image/backdrop/{int(r["id"])}"', 'f\'/tmdb-image/backdrop/{int(r["id"])}\'')
if 'f"/tmdb-image/poster/{int(r["id"])}"' in text or 'f"/tmdb-image/backdrop/{int(r["id"])}"' in text:
    raise SystemExit("quote fix did not apply")
path.write_text(text, encoding="utf-8")
