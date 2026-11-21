import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';

/** Kompaktowy punkt z /aed-api/points: [szer, dł, indeks źródła, indeks dostępu, otwarte teraz (1/0/-1)] */
export type AedPoint = [number, number, number, number, number];

export interface AedPoints {
  generated: string;
  sources: string[];
  access: string[];
  points: AedPoint[];
}

export interface AedDetail {
  idx: number;
  id_aed: string;
  nazwa_obiektu: string;
  opis_lokalizacji: string;
  adres: string;
  szerokosc: number;
  dlugosc: number;
  wewnatrz: boolean | null;
  pietro: string;
  dostep: string;
  dostep_opis: string;
  godziny_dostepnosci: string;
  otwarte_teraz: boolean | null;
  dysponent: string;
  data_weryfikacji: string;
  zrodlo: string;
  zrodlo_url: string;
  licencja: string;
  zbior: string;
}

export interface AedStats {
  aed_razem: number;
  aed_dane_gov_pl: number;
  aed_demo_osm: number;
  dostepne_teraz: number;
  zbiory_dane_gov_pl: number;
}

export interface NearestHit {
  idx: number;
  dist: number;
  walkMin: number;
  bearing: number;
  status: AedStatus;
}

export type AedStatus = 'open' | 'unknown' | 'closed';

export interface AedFilters {
  onlyAvailable: boolean;
  onlyPublic: boolean;
  sources: Set<string>;
}

const WALK_M_PER_MIN = 83; // ok. 5 km/h
const DETOUR = 1.3; // trasa piesza jest dłuższa niż linia prosta

export const SOURCE_LABEL: Record<string, string> = {
  danegov: 'dane.gov.pl',
  osm: 'OpenStreetMap (demo)',
};

@Injectable({ providedIn: 'root' })
export class AedService {
  private readonly http = inject(HttpClient);
  private readonly api = '/aed-api';
  private points$?: Observable<AedPoints>;
  private details = new Map<number, Observable<AedDetail>>();

  points(force = false): Observable<AedPoints> {
    if (!this.points$ || force) {
      this.points$ = this.http.get<AedPoints>(`${this.api}/points`).pipe(shareReplay(1));
    }
    return this.points$;
  }

  detail(idx: number): Observable<AedDetail> {
    if (!this.details.has(idx)) {
      this.details.set(idx, this.http.get<AedDetail>(`${this.api}/aed/${idx}`).pipe(shareReplay(1)));
    }
    return this.details.get(idx)!;
  }

  stats(): Observable<AedStats> {
    return this.http.get<AedStats>(`${this.api}/stats`);
  }

  sources(): Observable<any> {
    return this.http.get(`${this.api}/sources`);
  }

  refresh(): Observable<any> {
    this.details.clear();
    return this.http.post(`${this.api}/refresh`, {});
  }

  verifyPhoto(file: File, lat?: number, lon?: number): Observable<any> {
    const q = lat !== undefined && lon !== undefined ? `?lat=${lat}&lon=${lon}` : '';
    return this.http.post(`${this.api}/zdjecie${q}`, file, {
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
    });
  }

  submit(payload: Record<string, unknown>): Observable<any> {
    return this.http.post(`${this.api}/zgloszenia`, payload);
  }

  // ------------------------------------------------------------------ obliczenia (po stronie przeglądarki)

  status(data: AedPoints, p: AedPoint): AedStatus {
    if (data.access[p[3]] === 'prywatny' || p[4] === 0) return 'closed';
    return p[4] === 1 ? 'open' : 'unknown';
  }

  passes(data: AedPoints, p: AedPoint, f: AedFilters): boolean {
    if (!f.sources.has(data.sources[p[2]])) return false;
    if (f.onlyPublic && data.access[p[3]] !== 'publiczny') return false;
    if (f.onlyAvailable && this.status(data, p) === 'closed') return false;
    return true;
  }

  nearest(data: AedPoints, lat: number, lon: number, n: number, f: AedFilters): NearestHit[] {
    const out: NearestHit[] = [];
    const pts = data.points;
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      if (Math.abs(p[0] - lat) > 0.5 || Math.abs(p[1] - lon) > 0.8) continue;
      if (!this.passes(data, p, f)) continue;
      const dist = haversine(lat, lon, p[0], p[1]);
      out.push({ idx: i, dist, walkMin: walkMinutes(dist), bearing: bearing(lat, lon, p[0], p[1]), status: this.status(data, p) });
    }
    out.sort((a, b) => a.dist - b.dist);
    return out.slice(0, n);
  }
}

// ------------------------------------------------------------------ geometria

export function haversine(a: number, b: number, c: number, d: number): number {
  const R = 6371000;
  const r = Math.PI / 180;
  const dp = (c - a) * r;
  const dl = (d - b) * r;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

export function bearing(a: number, b: number, c: number, d: number): number {
  const r = Math.PI / 180;
  const y = Math.sin((d - b) * r) * Math.cos(c * r);
  const x = Math.cos(a * r) * Math.sin(c * r) - Math.sin(a * r) * Math.cos(c * r) * Math.cos((d - b) * r);
  return (Math.atan2(y, x) / r + 360) % 360;
}

export function walkMinutes(m: number): number {
  return Math.max(1, Math.round((m * DETOUR) / WALK_M_PER_MIN));
}

export function formatDistance(m: number): string {
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1).replace('.', ',')} km`;
}

export function compassName(deg: number): string {
  const names = ['północ', 'północny wschód', 'wschód', 'południowy wschód', 'południe', 'południowy zachód', 'zachód', 'północny zachód'];
  return names[Math.round(deg / 45) % 8];
}

export function aedTitle(d: AedDetail): string {
  if (d.nazwa_obiektu) return d.nazwa_obiektu;
  if (d.dysponent) return d.dysponent;
  if (d.adres) return `AED – ${d.adres}`;
  return 'Defibrylator AED';
}

export function navUrl(fromLat: number | null, fromLon: number | null, lat: number, lon: number): string {
  return fromLat !== null && fromLon !== null
    ? `https://www.google.com/maps/dir/?api=1&origin=${fromLat},${fromLon}&destination=${lat},${lon}&travelmode=walking`
    : `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
}

export const STATUS_TEXT: Record<AedStatus, string> = {
  open: 'Dostępny teraz',
  unknown: 'Godziny nieznane',
  closed: 'Zamknięty lub prywatny',
};
