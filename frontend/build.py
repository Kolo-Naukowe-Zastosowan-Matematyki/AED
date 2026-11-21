"""Strefa 3: wbudowanie modułu AED we frontend portalu dane.gov.pl i zbudowanie go.

    python frontend/build.py                      # źródła portalu z ../material/frontend_latest.zip
    python frontend/build.py --portal ŚCIEŻKA     # własna kopia repozytorium frontendu
    python frontend/build.py --only-patch         # tylko wgraj moduł, bez budowania

Co robi:
  1. kopiuje frontend/portal-module/src/app/pages/aed do src/app/pages/aed portalu,
  2. dopisuje trasę /pl/aed w app-routing.module.ts (lazy loading, jak inne moduły portalu),
  3. dodaje pozycję „Mapa AED” w menu głównym (header.component.html),
  4. dodaje baner akcji na stronie głównej (home.component.*) i wyłącza modal RODO w trybie /aed/teraz,
  5. dodaje tłumaczenia (pl.json, en.json) i konfigurację budowania „aed” (angular.json),
  6. uruchamia `npm ci` (jeśli trzeba) i `ng build --configuration aed`,
  7. kopiuje wynik do frontend/dist, skąd serwuje go `python server.py`.
Każda zmiana jest oznaczona komentarzem „AED-MODULE”, a skrypt można uruchamiać wielokrotnie.
Wymaga Node.js 20+ i npm.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODULE = HERE / "portal-module" / "src" / "app" / "pages" / "aed"
MARK = "AED-MODULE"

ROUTE = """      // AED-MODULE: moduł „Mapa AED”
      {
        path: '!aed',
        data: { breadcrumbs: { translationKey: 'Aed.Self' } },
        loadChildren: () => import('./pages/aed/aed.routes').then((m) => m.AED_ROUTES),
      },
"""

MENU = """            <!-- AED-MODULE: Mapa AED -->
            <li class="nav-item" role="presentation">
              <a
                class="nav-link"
                role="menuitem"
                [routerLink]="['/!aed'] | localize"
                routerLinkActive="active"
                #menuLinkAed="routerLinkActive"
                [attr.aria-current]="menuLinkAed.isActive ? true : null">
                {{ 'Menu.Aed' | translate }}
              </a>
            </li>

"""

I18N = {
    "pl": {"Self": "Mapa AED", "Emergency": "Znajdź AED teraz", "Browse": "Mapa i lista", "Help": "Jak udzielić pomocy",
           "Report": "Zgłoś AED", "Data": "Dane i źródła", "Menu": "Mapa AED"},
    "en": {"Self": "AED map", "Emergency": "Find an AED now", "Browse": "Map and list", "Help": "How to help",
           "Report": "Report an AED", "Data": "Data and sources", "Menu": "AED map"},
}


def patch_text(path: Path, anchor: str, insert: str, before: bool = True) -> None:
    text = path.read_text(encoding="utf-8")
    if MARK in text and insert.strip().splitlines()[0].strip() in text:
        return
    if anchor not in text:
        raise SystemExit(f"Nie znaleziono miejsca wstawienia w {path}: {anchor!r}")
    text = text.replace(anchor, insert + anchor if before else anchor + insert, 1)
    path.write_text(text, encoding="utf-8")


def patch(portal: Path) -> None:
    app = portal / "src" / "app"
    dst = app / "pages" / "aed"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(MODULE, dst)

    patch_text(app / "app-routing.module.ts", "      {\n        path: '!user',", ROUTE)
    patch_text(app / "layout" / "header" / "header.component.html", "            <!-- institutions -->", MENU)

    home_ts = app / "pages" / "home" / "home.component.ts"
    t = home_ts.read_text(encoding="utf-8")
    if "AedHomeBannerComponent" not in t:
        t = t.replace("import { NgIf } from '@angular/common';",
                      "import { NgIf } from '@angular/common';\n// AED-MODULE\n"
                      "import { AedHomeBannerComponent } from '@app/pages/aed/aed-home-banner/aed-home-banner.component';", 1)
        t = t.replace("  imports: [", "  imports: [\n    AedHomeBannerComponent,", 1)
        home_ts.write_text(t, encoding="utf-8")
    # Tryb ratunkowy (/aed/teraz) nie może być zasłonięty modalem RODO przy pierwszej wizycie.
    # Modal nie jest oznaczany jako przeczytany, więc pokaże się przy następnej zwykłej wizycie.
    footer = app / "layout" / "footer" / "footer.component.ts"
    f = footer.read_text(encoding="utf-8")
    if MARK not in f:
        f = f.replace("      if (this.isAcquintedWithRodo) {",
                      "      // AED-MODULE: nie zasłaniaj trybu ratunkowego modalem RODO\n"
                      "      if (this.isAcquintedWithRodo || window.location.pathname.includes('/aed/teraz')) {", 1)
        footer.write_text(f, encoding="utf-8")
    patch_text(app / "pages" / "home" / "home.component.html", "<!-- SEARCH and SUGGESTIONS -->",
               "<!-- AED-MODULE: baner akcji -->\n<home-aed-banner></home-aed-banner>\n\n")

    for lang, vals in I18N.items():
        p = portal / "src" / "assets" / "i18n" / f"{lang}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["Aed"] = {k: v for k, v in vals.items() if k != "Menu"}
        d.setdefault("Menu", {})["Aed"] = vals["Menu"]
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ang = portal / "angular.json"
    a = json.loads(ang.read_text(encoding="utf-8"))
    proj = next(iter(a["projects"].values()))
    proj["architect"]["build"]["configurations"]["aed"] = {
        "budgets": [{"type": "initial", "maximumWarning": "5mb", "maximumError": "8mb"}],
        "outputHashing": "all",
        "sourceMap": False,
    }
    ang.write_text(json.dumps(a, indent=2) + "\n", encoding="utf-8")
    print(f"Moduł AED wgrany do: {portal}")


def build(portal: Path) -> None:
    npm = "npm.cmd" if sys.platform.startswith("win") else "npm"
    npx = "npx.cmd" if sys.platform.startswith("win") else "npx"
    env = {**__import__("os").environ, "PUPPETEER_SKIP_DOWNLOAD": "1"}
    if not (portal / "node_modules").exists():
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=portal, check=True, env=env)
    subprocess.run([npx, "ng", "build", "--configuration", "aed"], cwd=portal, check=True, env=env)
    out = portal / "dist" / "frontend" / "browser"
    dist = HERE / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(out, dist)
    print(f"Gotowe: {dist}  ->  uruchom `python server.py`")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", type=Path, help="katalog ze źródłami frontendu portalu")
    ap.add_argument("--only-patch", action="store_true")
    args = ap.parse_args()
    portal = args.portal
    if portal is None:
        portal = HERE / "_portal_src"
        if not (portal / "angular.json").exists():
            z = ROOT.parent / "material" / "frontend_latest.zip"
            print(f"Rozpakowuję {z} do {portal}")
            with zipfile.ZipFile(z) as zf:
                zf.extractall(portal)
    patch(portal.resolve())
    if not args.only_patch:
        build(portal.resolve())


if __name__ == "__main__":
    main()
