"""Strefa 4: wstępna weryfikacja zdjęcia zgłoszonego AED.

Cel: odsiać oczywiste pomyłki i spam ZANIM zgłoszenie trafi do moderatora / dysponenta.
Wynik to podpowiedź, nie decyzja: zgłoszenie zawsze sprawdza człowiek.

Kroki:
  1. Plik: format (JPEG/PNG/WEBP), rozmiar, rozdzielczość.
  2. Jakość: ostrość (wariancja krawędzi), jasność.
  3. Metadane EXIF: data wykonania i współrzędne GPS (porównanie z lokalizacją ze zgłoszenia).
  4. Duplikaty: skrót percepcyjny dHash (to samo zdjęcie zgłoszone kilka razy).
  5. Znak AED: detektor zielonej tablicy w kolorystyce znaku ISO 7010 E010 z jasnym symbolem w środku
     (heurystyka kolorystyczna, bez modelu ML). Opcjonalnie model zero-shot CLIP, jeśli zainstalowano
     `transformers` i `torch` (patrz vision/README.md).

Wymaga Pillow (`pip install -r vision/requirements.txt`). Bez Pillow zwraca czytelną informację
i reszta modułu działa dalej.
"""
from __future__ import annotations

import io
import math
from collections import deque
from datetime import datetime

try:
    from PIL import ExifTags, Image, ImageFilter, ImageOps, ImageStat
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

MAX_BYTES = 8 * 1024 * 1024
MIN_SIDE = 320
_CLIP = None  # leniwie ładowany model (opcjonalny)


# ------------------------------------------------------------------ pomocnicze

def _gps_to_deg(values, ref) -> float | None:
    try:
        d, m, s = (float(v) for v in values)
        deg = d + m / 60 + s / 3600
        return -deg if ref in ("S", "W") else deg
    except Exception:  # noqa: BLE001
        return None


def _exif(img) -> dict:
    out: dict = {}
    try:
        ex = img.getexif()
    except Exception:  # noqa: BLE001
        return out
    if not ex:
        return out
    tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
    dt = tags.get("DateTime")
    try:
        sub = ex.get_ifd(0x8769)  # Exif IFD
        dt = sub.get(36867) or dt  # DateTimeOriginal
    except Exception:  # noqa: BLE001
        pass
    if dt:
        out["data_wykonania"] = str(dt).replace(":", "-", 2)
    try:
        gps = ex.get_ifd(0x8825)
        if gps:
            lat = _gps_to_deg(gps.get(2), gps.get(1))
            lon = _gps_to_deg(gps.get(4), gps.get(3))
            if lat is not None and lon is not None:
                out["gps"] = [round(lat, 6), round(lon, 6)]
    except Exception:  # noqa: BLE001
        pass
    return out


def dhash(img, size: int = 8) -> str:
    g = img.convert("L").resize((size + 1, size), Image.BILINEAR)
    px = list(g.getdata())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | (px[r * (size + 1) + c] > px[r * (size + 1) + c + 1])
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _haversine_m(a, b) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


# ------------------------------------------------------------------ detektor znaku AED

def _is_sign_green(h, s, v) -> bool:
    # zieleń bezpieczeństwa (ISO 7010, ok. RGB 0,154,73 -> H≈105..115 w skali 0..255 Pillow)
    return 80 <= h <= 135 and s >= 110 and 60 <= v <= 235


def detect_aed_sign(img) -> dict:
    """Szuka największego zielonego, zwartego obszaru z jasnym symbolem w środku."""
    w0, h0 = img.size
    scale = 160 / max(w0, h0)
    small = img.convert("RGB").resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))), Image.BILINEAR)
    hsv = small.convert("HSV")
    W, H = small.size
    px = hsv.load()
    green = [[_is_sign_green(*px[x, y]) for x in range(W)] for y in range(H)]

    # największa spójna składowa zielonych pikseli (BFS)
    seen = [[False] * W for _ in range(H)]
    best = None
    for y in range(H):
        for x in range(W):
            if green[y][x] and not seen[y][x]:
                q = deque([(x, y)])
                seen[y][x] = True
                n, x0, y0, x1, y1 = 0, x, y, x, y
                while q:
                    cx, cy = q.popleft()
                    n += 1
                    x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < W and 0 <= ny < H and green[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            q.append((nx, ny))
                if best is None or n > best[0]:
                    best = (n, x0, y0, x1, y1)
    if not best:
        return {"wynik": 0.0, "powod": "brak zielonego obszaru w kolorystyce znaku AED"}

    n, x0, y0, x1, y1 = best
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    area = bw * bh / (W * H)                # udział ramki w kadrze
    fill = n / (bw * bh)                    # jak bardzo zwarty jest zielony obszar
    aspect = bw / bh
    # jasne piksele (biały symbol serca/błyskawicy) wewnątrz ramki
    white = sum(1 for yy in range(y0, y1 + 1) for xx in range(x0, x1 + 1)
                if (lambda h, s, v: s < 70 and v > 190)(*px[xx, yy]))
    white_ratio = white / (bw * bh)

    score = 0.0
    score += 0.35 * min(1.0, area / 0.03) if area >= 0.004 else 0.0       # wystarczająco duży
    score += 0.2 if 0.5 <= aspect <= 2.0 else 0.0                         # tablica, nie pas zieleni
    score += 0.2 * min(1.0, fill / 0.6)                                   # zwarty obszar
    score += 0.25 if 0.06 <= white_ratio <= 0.55 else 0.0                 # jasny symbol w środku
    if area > 0.85 and white_ratio < 0.03:                                # np. zdjęcie trawnika
        score *= 0.3
    return {
        "wynik": round(min(score, 1.0), 2),
        "ramka": [round(x0 / scale), round(y0 / scale), round((x1 + 1) / scale), round((y1 + 1) / scale)],
        "udzial_w_kadrze": round(area, 3),
        "jasny_symbol": round(white_ratio, 3),
    }


def _clip_score(img) -> float | None:
    """Opcjonalnie: zero-shot CLIP. Zwraca None, gdy biblioteki nie są zainstalowane."""
    global _CLIP
    try:
        if _CLIP is None:
            from transformers import pipeline  # type: ignore
            _CLIP = pipeline("zero-shot-image-classification", model="openai/clip-vit-base-patch32")
        labels = ["an AED defibrillator or its green wall sign", "an empty wall", "a random object", "a person"]
        res = _CLIP(img.convert("RGB"), candidate_labels=labels)
        return round(next(r["score"] for r in res if r["label"] == labels[0]), 2)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ główna funkcja

def verify(data: bytes, declared: tuple[float, float] | None = None, known_hashes: list[str] | None = None,
           use_clip: bool = False) -> dict:
    """Zwraca ocenę zdjęcia. `ocena`: 'prawdopodobnie_aed' | 'niepewne' | 'odrzuc' | 'brak_weryfikacji'."""
    if not HAVE_PIL:
        return {"ocena": "brak_weryfikacji", "uwagi": ["Weryfikacja zdjęć wymaga biblioteki Pillow "
                                                        "(pip install -r vision/requirements.txt)."]}
    notes: list[str] = []
    if len(data) > MAX_BYTES:
        return {"ocena": "odrzuc", "uwagi": ["Plik jest większy niż 8 MB."]}
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001
        return {"ocena": "odrzuc", "uwagi": ["To nie jest obsługiwany obraz (JPEG, PNG lub WEBP)."]}
    fmt = img.format or ""
    exif = _exif(img)
    img = ImageOps.exif_transpose(img)
    w, h = img.size
    out: dict = {"format": fmt, "rozmiar": [w, h], "exif": exif}

    if fmt not in ("JPEG", "PNG", "WEBP", "MPO"):
        notes.append(f"Nietypowy format: {fmt}.")
    if min(w, h) < MIN_SIDE:
        notes.append("Zdjęcie ma zbyt małą rozdzielczość.")

    gray = img.convert("L").resize((min(512, w), max(1, int(h * min(512, w) / w))))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))  # bez artefaktów na brzegach kadru
    sharp = ImageStat.Stat(edges).var[0]
    bright = ImageStat.Stat(gray).mean[0]
    out["jakosc"] = {"ostrosc": round(sharp, 1), "jasnosc": round(bright, 1)}
    if sharp < 25:
        notes.append("Zdjęcie jest prawdopodobnie nieostre.")
    if bright < 35:
        notes.append("Zdjęcie jest bardzo ciemne.")

    if declared and exif.get("gps"):
        d = _haversine_m(declared, exif["gps"])
        out["odleglosc_gps_m"] = round(d)
        if d > 300:
            notes.append(f"Zdjęcie wykonano ok. {round(d)} m od wskazanej lokalizacji.")
    if exif.get("data_wykonania"):
        try:
            taken = datetime.strptime(exif["data_wykonania"][:10], "%Y-%m-%d")
            if (datetime.now() - taken).days > 3 * 365:
                notes.append("Zdjęcie ma ponad 3 lata – AED mógł zostać przeniesiony.")
        except ValueError:
            pass

    hsh = dhash(img)
    out["dhash"] = hsh
    if known_hashes and any(hamming(hsh, k) <= 5 for k in known_hashes):
        notes.append("Bardzo podobne zdjęcie zostało już zgłoszone (możliwy duplikat).")
        out["duplikat"] = True

    sign = detect_aed_sign(img)
    out["znak_aed"] = sign
    score = sign["wynik"]
    if use_clip:
        c = _clip_score(img)
        if c is not None:
            out["clip"] = c
            score = round(0.4 * score + 0.6 * c, 2)
    out["wynik"] = score

    if out.get("duplikat") or min(w, h) < MIN_SIDE // 2:
        verdict = "odrzuc"
    elif score >= 0.6:
        verdict = "prawdopodobnie_aed"
    else:
        verdict = "niepewne"
        notes.append("Nie widać wyraźnie zielonego znaku AED. Zrób zdjęcie, na którym widać urządzenie lub tablicę.")
    out["ocena"] = verdict
    out["uwagi"] = notes
    return out
