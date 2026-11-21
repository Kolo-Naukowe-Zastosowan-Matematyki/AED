"""Makieta portalu dane.gov.pl: oryginalny frontend portalu z minimalną zmianą dla zbioru AED, zbudowany do dist/.

    python portal/frontend/build.py                      # źródła portalu z ../material/frontend_latest.zip
    python portal/frontend/build.py --portal ŚCIEŻKA     # własna kopia repozytorium frontendu
    python portal/frontend/build.py --only-patch         # tylko zmiany w źródłach, bez budowania

Sam zbiór „System Ewidencji Zasobów AED” nie wymaga zmian we frontendzie: wyświetlają go oryginalne komponenty
portalu z danymi z portal/backend/aed_dataset.py. Jedyna zmiana w kodzie portalu to link „Przejdź: Strona
internetowa” obok „Pobierz” przy zasobach typu plik, które mają osobną stronę w serwisie AED (Rejestr AED,
Mapa AED), na liście zasobów i na stronie zasobu. Zmiany są oznaczone komentarzem „AED-MODULE”.
Skrypt dodaje też konfigurację budowania „aed” (angular.json), uruchamia `npm ci` (jeśli trzeba)
i `ng build --configuration aed`, a wynik kopiuje do portal/frontend/dist. Wymaga Node.js 20+ i npm.
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
ROOT = HERE.parents[1]
MARK = "AED-MODULE"

# Link do podstrony zasobu AED (atrybut aed_page_url z backend/aed_dataset.py) obok „Pobierz”.
LIST_LINK = """  <!-- AED-MODULE: link do podstrony zasobu AED -->
  <ng-container *ngIf="item.attributes.media_type === 'file' && item.attributes.aed_page_url">
    <div class="font-weight-bold mt-lg-2 ml-3 ml-lg-0">{{ 'Action.Go' | translate }}:</div>
    <a class="underline ml-3 ml-lg-0" target="_blank" href="{{ item.attributes.aed_page_url }}">
      {{ 'TypesFilters.Website' | translate }} <span aria-hidden="true">>></span>
      <span class="visually-hidden">{{ item?.attributes?.title }} {{ 'SkipTo.NewWindow' | translate }}</span>
    </a>
  </ng-container>

"""
RESOURCE_LINK = """          <!-- AED-MODULE: link do podstrony zasobu AED -->
          <div class="d-flex align-items-center mb-1"
               *ngIf="resource?.attributes?.media_type === 'file' && resource?.attributes?.aed_page_url">
            <span class="font-weight-bold" style="min-width: 85px"> {{ 'Action.Go' | translate }}: </span>
            <a class="btn btn-primary btn-sm" target="_blank" href="{{ resource.attributes.aed_page_url }}">
              {{ 'TypesFilters.Website' | translate }} <span aria-hidden="true">>></span>
              <span class="visually-hidden">{{ 'SkipTo.NewWindow' | translate }}</span>
            </a>
          </div>

"""


def patch_text(path: Path, anchor: str, insert: str, before: bool = True) -> None:
    text = path.read_text(encoding="utf-8")
    if MARK in text and insert.strip().splitlines()[0].strip() in text:
        return
    if anchor not in text:
        raise SystemExit(f"Nie znaleziono miejsca wstawienia w {path}: {anchor!r}")
    text = text.replace(anchor, insert + anchor if before else anchor + insert, 1)
    path.write_text(text, encoding="utf-8")


def patch(portal: Path) -> None:
    ds = portal / "src" / "app" / "pages" / "dataset"
    patch_text(ds / "resource-list" / "resource-item-files-download" / "resource-item-files-download.component.html",
               "  <!-- resource api -->", LIST_LINK)
    patch_text(ds / "dataset-resource" / "dataset-resource.component.html", "          <!-- See tabular data JSON -->",
               RESOURCE_LINK)

    ang = portal / "angular.json"
    a = json.loads(ang.read_text(encoding="utf-8"))
    proj = next(iter(a["projects"].values()))
    proj["architect"]["build"]["configurations"]["aed"] = {
        "budgets": [{"type": "initial", "maximumWarning": "5mb", "maximumError": "8mb"}],
        "outputHashing": "all",
        "sourceMap": False,
    }
    ang.write_text(json.dumps(a, indent=2) + "\n", encoding="utf-8")
    print(f"Zmiany dla zbioru AED wgrane do: {portal}")


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
