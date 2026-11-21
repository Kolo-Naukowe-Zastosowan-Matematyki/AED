"""Powiat i gmina rekordu z rejestru TERC (GUS, TERYT), do wyszukiwania po obszarze.

Słownik to plik TERC w wersji urzędowej z eteryt.stat.gov.pl (CSV „;”: WOJ;POW;GMI;RODZ;NAZWA;NAZWA_DOD;STAN_NA),
zapisany jako common/teryt_terc.csv (albo dowolny common/TERC*.csv). Bez pliku wyszukiwanie po powiatach i gminach
jest po prostu niedostępne; województwa działają zawsze (kolumna region).

Gminę rozpoznajemy po nazwie miejscowości w obrębie województwa: najpierw gmina miejska (w tym miasta na prawach
powiatu), potem miasto w gminie miejsko-wiejskiej, gmina miejsko-wiejska i wiejska o tej samej nazwie.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from rozwiazanie.scraping.standard import TERYT_WOJ, norm

KOLEJNOSC_RODZ = {"1": 0, "4": 1, "3": 2, "2": 3}  # gmina miejska, miasto w gm. m-w, gmina m-w, gmina wiejska
WOJ_KOD = {v: k for k, v in TERYT_WOJ.items()}


def _czytaj(raw: bytes) -> list[dict]:
    for enc in ("utf-8-sig", "cp1250"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return [{(k or "").strip().upper(): (v or "").strip() for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(text), delimiter=";")]


class Terc:
    def __init__(self, rows: list[dict]):
        self.powiaty: dict[tuple[str, str], str] = {}
        self.gminy: dict[tuple[str, str], list[tuple[int, str, str, str]]] = {}
        for r in rows:
            woj, pow_, gmi, rodz = r.get("WOJ", ""), r.get("POW", ""), r.get("GMI", ""), r.get("RODZ", "")
            nazwa, dod = r.get("NAZWA", ""), r.get("NAZWA_DOD", "").lower()
            if not (woj and pow_ and nazwa):
                continue
            if not gmi:
                self.powiaty[(woj, pow_)] = f"{nazwa} (miasto na prawach powiatu)" if "miasto" in dod \
                    else f"powiat {nazwa}"
            elif rodz in KOLEJNOSC_RODZ:
                self.gminy.setdefault((woj, norm(nazwa)), []).append((KOLEJNOSC_RODZ[rodz], pow_, gmi, nazwa))

    @classmethod
    def z_katalogu(cls, katalog: Path) -> "Terc | None":
        pliki = sorted(katalog.glob("teryt_terc.csv")) + sorted(katalog.glob("TERC*.csv"))
        return cls(_czytaj(pliki[0].read_bytes())) if pliki else None

    def obszar(self, city: str, region: str) -> dict:
        """{"powiat": "powiat legionowski", "gmina": "gmina Legionowo"} albo {} gdy nie wiadomo."""
        if not city:
            return {}
        woj_lista = [WOJ_KOD[region]] if region in WOJ_KOD else sorted(TERYT_WOJ)
        traf = [(w, g) for w in woj_lista for g in self.gminy.get((w, norm(city)), [])]
        if not traf:
            return {}
        if len({w for w, _ in traf}) > 1:  # ta sama nazwa w kilku województwach, a województwa nie znamy
            return {}
        woj, (_, pow_, _, nazwa) = min(traf, key=lambda t: t[1][0])
        powiat = self.powiaty.get((woj, pow_), "")
        return {"powiat": powiat, "gmina": f"gmina {nazwa}"} if powiat else {"gmina": f"gmina {nazwa}"}
