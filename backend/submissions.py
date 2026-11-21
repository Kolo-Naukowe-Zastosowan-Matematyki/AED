"""Zgłoszenia AED od użytkowników: zapis do kolejki moderacji (nie trafiają automatycznie do zbioru).

Zdjęcie jest najpierw sprawdzane przez strefę 4 (vision.verify), wynik zapisujemy przy zgłoszeniu,
żeby moderator / dysponent widział wstępną ocenę. Nie zapisujemy danych osobowych zgłaszającego.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

MAX_PHOTO = 8 * 1024 * 1024
ALLOWED_FIELDS = ("szerokosc", "dlugosc", "nazwa_obiektu", "opis_lokalizacji", "godziny_dostepnosci", "dostep",
                  "wewnatrz", "pietro", "dysponent", "zdjecie_id", "zgoda_regulamin")


class Submissions:
    def __init__(self, base: Path):
        self.dir = base / "data" / "zgloszenia"
        self.photos = self.dir / "zdjecia"
        self.photos.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def save_photo(self, data: bytes, verdict: dict) -> str:
        pid = uuid.uuid4().hex[:16]
        ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(verdict.get("format", ""), "bin")
        (self.photos / f"{pid}.{ext}").write_bytes(data)
        (self.photos / f"{pid}.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
        return pid

    def photo_verdict(self, pid: str) -> dict | None:
        p = self.photos / f"{pid}.json"
        if not pid.isalnum() or not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def add(self, payload: dict) -> dict:
        rec = {k: payload.get(k) for k in ALLOWED_FIELDS if k in payload}
        lat, lon = rec.get("szerokosc"), rec.get("dlugosc")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            raise ValueError("Brak lokalizacji AED")
        if not (rec.get("opis_lokalizacji") or "").strip():
            raise ValueError("Opisz, gdzie dokładnie wisi AED")
        rec["id"] = uuid.uuid4().hex[:12]
        rec["status"] = "do_weryfikacji"
        rec["utworzono"] = datetime.now().isoformat(timespec="seconds")
        if rec.get("zdjecie_id"):
            rec["weryfikacja_zdjecia"] = self.photo_verdict(str(rec["zdjecie_id"]))
        with self.lock:
            (self.dir / f"{rec['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec

    def list(self) -> list[dict]:
        items = []
        for p in sorted(self.dir.glob("*.json"), reverse=True):
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return items
