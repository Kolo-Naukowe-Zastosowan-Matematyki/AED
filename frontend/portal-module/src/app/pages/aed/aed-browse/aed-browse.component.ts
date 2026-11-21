import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { SeoService } from '@app/services/seo.service';
import { AedMapComponent } from '../aed-map/aed-map.component';
import {
  AedDetail,
  AedFilters,
  AedPoints,
  AedService,
  NearestHit,
  STATUS_TEXT,
  aedTitle,
  formatDistance,
  haversine,
  navUrl,
  walkMinutes,
} from '../aed.service';
import { geocodeAddress } from '../geocode';

/** Przeglądanie: pełnej szerokości mapa, pod nią lista najbliższych. Bez bocznego panelu. */
@Component({
  selector: 'app-aed-browse',
  standalone: true,
  imports: [FormsModule, AedMapComponent],
  templateUrl: './aed-browse.component.html',
  styleUrls: ['../aed.scss', './aed-browse.component.scss'],
})
export class AedBrowseComponent implements OnInit {
  private readonly aed = inject(AedService);
  private readonly seo = inject(SeoService);

  readonly data = signal<AedPoints | null>(null);
  readonly filters = signal<AedFilters>({ onlyAvailable: false, onlyPublic: false, sources: new Set(['danegov', 'osm']) });
  readonly user = signal<[number, number] | null>(null);
  readonly list = signal<NearestHit[]>([]);
  readonly details = signal<Record<number, AedDetail>>({});
  readonly selected = signal<AedDetail | null>(null);
  readonly selectedDist = signal<number | null>(null);
  readonly visibleCount = signal(0);
  readonly error = signal('');
  address = '';
  locating = false;

  readonly statusText = STATUS_TEXT;
  readonly title = aedTitle;
  readonly fmt = formatDistance;

  ngOnInit(): void {
    this.seo.setPageTitle(['Mapa i lista AED', 'Mapa AED']);
    this.aed.points().subscribe({
      next: (d) => {
        this.data.set(d);
        this.recount();
      },
      error: () => this.error.set('Nie udało się pobrać danych o AED.'),
    });
  }

  toggle(key: 'onlyAvailable' | 'onlyPublic'): void {
    this.filters.set({ ...this.filters(), [key]: !this.filters()[key] });
    this.refresh();
  }

  toggleSource(src: string): void {
    const s = new Set(this.filters().sources);
    s.has(src) ? s.delete(src) : s.add(src);
    this.filters.set({ ...this.filters(), sources: s });
    this.refresh();
  }

  hasSource(src: string): boolean {
    return this.filters().sources.has(src);
  }

  locate(): void {
    if (!navigator.geolocation) return;
    this.locating = true;
    navigator.geolocation.getCurrentPosition(
      (p) => {
        this.locating = false;
        this.setUser(p.coords.latitude, p.coords.longitude);
      },
      () => {
        this.locating = false;
        this.error.set('Nie udało się ustalić lokalizacji. Wpisz adres.');
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  }

  async search(): Promise<void> {
    if (!this.address.trim()) return;
    const hit = await geocodeAddress(this.address);
    if (!hit) {
      this.error.set('Nie znaleziono adresu.');
      return;
    }
    this.error.set('');
    this.setUser(hit.lat, hit.lon);
  }

  select(idx: number): void {
    const d = this.data();
    const u = this.user();
    if (d && u) this.selectedDist.set(haversine(u[0], u[1], d.points[idx][0], d.points[idx][1]));
    else this.selectedDist.set(null);
    this.aed.detail(idx).subscribe((x) => this.selected.set(x));
  }

  walk(m: number): number {
    return walkMinutes(m);
  }

  nav(d: AedDetail): string {
    const u = this.user();
    return navUrl(u ? u[0] : null, u ? u[1] : null, d.szerokosc, d.dlugosc);
  }

  private setUser(lat: number, lon: number): void {
    this.user.set([lat, lon]);
    this.refresh();
  }

  private refresh(): void {
    this.recount();
    const d = this.data();
    const u = this.user();
    if (!d || !u) return;
    const hits = this.aed.nearest(d, u[0], u[1], 10, this.filters());
    this.list.set(hits);
    hits.forEach((h) =>
      this.aed.detail(h.idx).subscribe((x) => this.details.set({ ...this.details(), [h.idx]: x })),
    );
  }

  private recount(): void {
    const d = this.data();
    if (!d) return;
    const f = this.filters();
    this.visibleCount.set(d.points.reduce((n, p) => n + (this.aed.passes(d, p, f) ? 1 : 0), 0));
  }
}
