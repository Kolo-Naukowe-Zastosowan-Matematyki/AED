"""Interaktywna mapa AED jako jeden plik HTML (zasób „Mapa AED” do pobrania).

Plik zawiera dane wszystkich punktów (tylko z dane.gov.pl), a bibliotekę Leaflet i podkład mapy wczytuje z internetu.
Ta sama strona jest podstroną /mapa serwisu AED. Po otwarciu: kliknięcie punktu pokazuje opis AED,
„Znajdź najbliższe” pokazuje użytkownika i najbliższy AED, „Strona główna” wraca do rejestru.
"""
from __future__ import annotations

import html
import json

from rozwiazanie.backend.schema import DOSTEP

TEMPLATE = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b3152">
<title>Mapa AED — __TITLE__</title>
__LEAFLET_CSS__
<style>
  :root { font-family: "Segoe UI", Arial, sans-serif; color: #242a30; background: #f3f4f5;
          --blue: #0066a4; --navy: #082d4b; --orange: #d72d00; }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; min-width: 320px; }
  body { display: flex; flex-direction: column; }
  a { color: var(--blue); }
  /* nagłówek jak na stronie rejestru */
  .topbar { flex: none; height: 58px; background: #fff; border-bottom: 1px solid #d5d9dc; }
  .topbar__inner { width: min(1120px, calc(100% - 32px)); height: 100%; margin: auto;
                   display: flex; align-items: center; gap: 18px; }
  .brand-mark { width: 44px; height: 42px; display: grid; place-items: center; background: #d40024; color: #fff;
                font-weight: 800; letter-spacing: .03em; }
  .brand { color: #20252a; font-family: Georgia, serif; font-size: 21px; text-decoration: none; }
  .topbar__links { margin-left: auto; display: flex; gap: 26px; font-size: 14px; font-weight: 650; }
  .topbar__links a { text-decoration: none; }
  .topbar__links a[aria-current="page"] { color: #20252a; border-bottom: 3px solid var(--orange); padding-bottom: 3px; }
  .bar { flex: none; color: #fff; background: linear-gradient(118deg, #082844, #164f7d 72%, #0c3658); }
  .bar__inner { width: min(1120px, calc(100% - 32px)); margin: auto; padding: 12px 0; display: flex; flex-wrap: wrap;
                gap: 10px 18px; align-items: center; justify-content: space-between; }
  .bar h1 { margin: 0; font-size: 19px; }
  .bar p { margin: 2px 0 0; font-size: 13px; opacity: .9; }
  #locate { border: 0; min-height: 42px; padding: 0 18px; background: var(--orange); color: #fff; font: inherit;
            font-weight: 700; cursor: pointer; }
  #locate:hover { background: #b92500; }
  #map { flex: 1; min-height: 300px; }
  .actions { display: flex; flex-wrap: wrap; gap: 10px; }
  .home { display: inline-flex; align-items: center; min-height: 42px; padding: 0 16px; color: #fff; font-weight: 700;
          text-decoration: none; border: 2px solid #fff; }
  .home:hover { background: rgba(255, 255, 255, .12); }
  .popup h2 { font-size: 15px; margin: 0 0 4px; }
  .popup p { margin: 2px 0; font-size: 13px; }
  .popup a { font-weight: 700; }
  .me { background: #0865c9; border: 3px solid #fff; border-radius: 50%; box-shadow: 0 0 0 2px #0865c9; }
  button:focus-visible, a:focus-visible { outline: 3px solid #ffc400; outline-offset: 2px; }
  @media (max-width: 600px) { .topbar__links { gap: 12px; font-size: 13px; } .brand { font-size: 17px; } }
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar__inner">
    <div class="brand-mark" aria-hidden="true">AED</div>
    <a class="brand" href="__SITE__/">Rejestr AED</a>
    <nav class="topbar__links" aria-label="Nawigacja">
      <a href="__SITE__/mapa" aria-current="page">Mapa AED</a>
    </nav>
  </div>
</header>
<section class="bar">
  <div class="bar__inner">
    <div><h1>Mapa defibrylatorów AED</h1><p>__COUNT__ AED · dane na dzień __DATE__</p></div>
    <div class="actions">
      <a class="home" href="__SITE__/">&larr; Strona główna</a>
      <button id="locate" type="button">Znajdź najbliższe</button>
    </div>
  </div>
</section>
<div id="map" role="region" aria-label="Mapa defibrylatorów AED"></div>
__LEAFLET_JS__
<script>
var D = __DATA__; // [szer, dł, nazwa, opis miejsca, dostęp, godziny]
var map = L.map('map', { preferCanvas: true }).setView([52.07, 19.48], 6);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">współtwórcy OpenStreetMap</a>' }).addTo(map);
var esc = function (s) { return String(s || '').replace(/[&<>"]/g, function (c) {
  return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
var r = L.canvas({ padding: 0.3 });
var M = D.map(function (p) {
  return L.circleMarker([p[0], p[1]], { renderer: r, radius: 6, weight: 1.5, color: '#fff',
    fillColor: '#0a7d3e', fillOpacity: 1 })
   .bindPopup('<div class="popup"><h2>' + esc(p[2] || 'Defibrylator AED') + '</h2>' +
     (p[3] ? '<p>' + esc(p[3]) + '</p>' : '') +
     '<p>Dostęp: ' + esc(p[4]) + ' · godziny: ' + esc(p[5] || 'brak informacji') + '</p>' +
     '<p>Źródło: dane.gov.pl</p>' +
     '<p><a target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&travelmode=walking&destination=' +
     p[0] + ',' + p[1] + '">Prowadź do AED</a></p></div>').addTo(map);
});
function dist(a, b) {  // metry, wzór haversine
  var R = 6371000, r = Math.PI / 180, dl = (b[0] - a[0]) * r, dn = (b[1] - a[1]) * r;
  var h = Math.sin(dl / 2) * Math.sin(dl / 2) + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dn / 2) * Math.sin(dn / 2);
  return 2 * R * Math.asin(Math.sqrt(h));
}
var meMarker = null;
document.getElementById('locate').onclick = function () {
  if (!navigator.geolocation) return alert('Przeglądarka nie udostępnia lokalizacji.');
  navigator.geolocation.getCurrentPosition(function (pos) {
    var me = [pos.coords.latitude, pos.coords.longitude];
    if (meMarker) meMarker.remove();
    meMarker = L.marker(me, { icon: L.divIcon({ className: 'me', iconSize: [18, 18] }), title: 'Twoja lokalizacja' }).addTo(map);
    var best = -1, bestD = Infinity;
    D.forEach(function (p, i) { var d = dist(me, p); if (d < bestD) { bestD = d; best = i; } });
    if (best < 0) return map.setView(me, 16);
    map.fitBounds(L.latLngBounds([me, [D[best][0], D[best][1]]]).pad(0.4), { maxZoom: 17 });
    M[best].openPopup();
  }, function () { alert('Nie udało się ustalić lokalizacji.'); }, { enableHighAccuracy: true, timeout: 8000 });
};
</script>
</body>
</html>
"""

# Leaflet 1.9.4 (BSD-2-Clause): na stronie serwisu z /vendor, w pliku do pobrania z unpkg (z sumą SRI).
LEAFLET_LOCAL = ('<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">', '<script src="/vendor/leaflet/leaflet.js"></script>')
LEAFLET_CDN = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"\n'
               '      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">',
               '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"\n'
               '        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>')



def build_map_html(records, title: str, date: str, site_url: str = "") -> bytes:
    """`site_url`: adres serwisu AED dla linków w nagłówku ("" = ten sam serwer, pełny adres w pliku do pobrania)."""
    data = [[round(r.szerokosc, 6), round(r.dlugosc, 6), r.nazwa_obiektu, r.opis_lokalizacji,
             DOSTEP.get(r.dostep, r.dostep), r.godziny_dostepnosci]
            for r in records]
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    css, js_tag = LEAFLET_CDN if site_url else LEAFLET_LOCAL
    out = (TEMPLATE.replace("__LEAFLET_CSS__", css).replace("__LEAFLET_JS__", js_tag).replace("__TITLE__", html.escape(title)).replace("__COUNT__", f"{len(records):,}".replace(",", " "))
           .replace("__DATE__", html.escape(date)).replace("__SITE__", html.escape(site_url.rstrip("/"), quote=True))
           .replace("__DATA__", js))
    return out.encode("utf-8")
