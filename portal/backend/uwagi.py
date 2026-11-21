"""„Zgłoś uwagi” do zbioru AED i jego zasobów w makiecie portalu.

W prawdziwym portalu uwaga (POST /datasets/<id>/comments, /resources/<id>/comments) trafia do dostawcy zbioru.
W makiecie trafia do katalogu data/uwagi, który przegląda dostawca. Kolejka nie jest dostępna przez API.
Imienia, nazwiska ani e-maila zgłaszającego nie zapisujemy.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

MAX_COMMENT = 5000


class Comments:
    def __init__(self, base: Path):
        self.dir = base / "data" / "uwagi"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def add(self, target: str, payload: dict) -> dict:
        """`payload` w formacie API portalu: {"data": {"type": "comment", "attributes": {"comment": ...}}}."""
        attrs = ((payload or {}).get("data") or {}).get("attributes") or {}
        comment = str(attrs.get("comment") or "").strip()
        if len(comment) < 3:
            raise ValueError("Treść uwagi jest za krótka")
        rec = {"id": uuid.uuid4().hex[:12], "dotyczy": target, "tresc": comment[:MAX_COMMENT],
               "status": "do_weryfikacji_przez_dostawce", "utworzono": datetime.now().isoformat(timespec="seconds")}
        with self.lock:
            (self.dir / f"{rec['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec

    def list(self) -> list[dict]:
        """Dla dostawcy (lokalnie, np. w testach). Nie jest wystawione w API."""
        items = []
        for p in sorted(self.dir.glob("*.json"), reverse=True):
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return items
