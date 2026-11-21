import { DOCUMENT, NgTemplateOutlet, isPlatformBrowser } from '@angular/common';
import { Component, OnDestroy, OnInit, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { LocalizeRouterPipe } from '@gilsdav/ngx-translate-router';

import { SeoService } from '@app/services/seo.service';
import { AedFirstAidComponent } from '../aed-first-aid/aed-first-aid.component';
import { AedMapComponent } from '../aed-map/aed-map.component';
import {
  AedDetail,
  AedFilters,
  AedPoints,
  AedService,
  NearestHit,
  STATUS_TEXT,
  aedTitle,
  compassName,
  formatDistance,
  navUrl,
} from '../aed.service';
import { geocodeAddress } from '../geocode';

type Phase = 'locating' | 'need-address' | 'searching' | 'ready' | 'none' | 'error';

/**
 * Tryb awaryjny: jeden ekran, jedna decyzja. Najbliższy dostępny AED, kierunek, czas dojścia
 * i przycisk „Prowadź”. Zakrywa resztę portalu, żeby nic nie rozpraszało.
 */
@Component({
  selector: 'app-aed-emergency',
  standalone: true,
  imports: [FormsModule, NgTemplateOutlet, RouterLink, LocalizeRouterPipe, AedMapComponent, AedFirstAidComponent],
  templateUrl: './aed-emergency.component.html',
  styleUrls: ['../aed.scss', './aed-emergency.component.scss'],
})
export class AedEmergencyComponent implements OnInit, OnDestroy {
  private readonly aed = inject(AedService);
  private readonly seo = inject(SeoService);
  private readonly doc = inject(DOCUMENT);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  readonly phase = signal<Phase>('locating');
  readonly data = signal<AedPoints | null>(null);
  readonly user = signal<[number, number] | null>(null);
  readonly hits = signal<NearestHit[]>([]);
  readonly pos = signal(0);
  readonly detail = signal<AedDetail | null>(null);
  readonly heading = signal<number | null>(null);
  readonly compassAvailable = signal(false);
  address = '';
  message = '';

  readonly hit = computed(() => this.hits()[this.pos()] ?? null);
  readonly arrow = computed(() => {
    const h = this.hit();
    if (!h) return 0;
    return h.bearing - (this.heading() ?? 0);
  });
  readonly filters: AedFilters = { onlyAvailable: true, onlyPublic: false, sources: new Set(['danegov', 'osm']) };
  readonly statusText = STATUS_TEXT;
  readonly title = aedTitle;
  readonly fmt = formatDistance;
  readonly compass = compassName;

  private orientationHandler = (e: any) => {
    const h = typeof e.webkitCompassHeading === 'number' ? e.webkitCompassHeading : e.absolute && e.alpha !== null ? 360 - e.alpha : null;
    if (h !== null) this.heading.set(h);
  };

  ngOnInit(): void {
    this.seo.setPageTitle(['Znajdź AED teraz', 'Mapa AED']);
    if (!this.isBrowser) return;
    this.doc.body.classList.add('aed-sos-open');
    this.aed.points().subscribe({
      next: (d) => {
        this.data.set(d);
        if (this.user()) this.search();
      },
      error: () => this.fail('Nie udało się pobrać danych o AED. Zadzwoń pod 112 – dyspozytor pomoże.'),
    });
    this.locate();
    this.compassAvailable.set('DeviceOrientationEvent' in window);
    if (typeof (window as any).DeviceOrientationEvent?.requestPermission !== 'function') this.enableCompass();
  }

  ngOnDestroy(): void {
    if (!this.isBrowser) return;
    this.doc.body.classList.remove('aed-sos-open');
    window.removeEventListener('deviceorientationabsolute', this.orientationHandler);
    window.removeEventListener('deviceorientation', this.orientationHandler);
  }

  locate(): void {
    if (!navigator.geolocation) {
      this.phase.set('need-address');
      return;
    }
    this.phase.set('locating');
    navigator.geolocation.getCurrentPosition(
      (p) => {
        this.user.set([p.coords.latitude, p.coords.longitude]);
        this.search();
      },
      () => this.phase.set('need-address'),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
    );
  }

  async useAddress(): Promise<void> {
    if (!this.address.trim()) return;
    this.phase.set('searching');
    const hit = await geocodeAddress(this.address);
    if (!hit) {
      this.message = 'Nie znaleziono adresu. Wpisz ulicę i miejscowość.';
      this.phase.set('need-address');
      return;
    }
    this.user.set([hit.lat, hit.lon]);
    this.search();
  }

  async enableCompass(): Promise<void> {
    const DOE = (window as any).DeviceOrientationEvent;
    try {
      if (typeof DOE?.requestPermission === 'function' && (await DOE.requestPermission()) !== 'granted') return;
    } catch {
      return;
    }
    window.addEventListener('deviceorientationabsolute', this.orientationHandler);
    window.addEventListener('deviceorientation', this.orientationHandler);
  }

  next(step: number): void {
    const n = this.hits().length;
    if (!n) return;
    this.pos.set((this.pos() + step + n) % n);
    this.loadDetail();
  }

  navLink(): string {
    const u = this.user();
    const d = this.detail();
    if (!d) return '#';
    return navUrl(u ? u[0] : null, u ? u[1] : null, d.szerokosc, d.dlugosc);
  }

  private search(): void {
    const d = this.data();
    const u = this.user();
    if (!d || !u) {
      this.phase.set('searching');
      return;
    }
    const hits = this.aed.nearest(d, u[0], u[1], 3, this.filters);
    this.hits.set(hits);
    this.pos.set(0);
    if (!hits.length) {
      this.phase.set('none');
      return;
    }
    this.loadDetail();
  }

  private loadDetail(): void {
    const h = this.hit();
    if (!h) return;
    this.aed.detail(h.idx).subscribe({
      next: (d) => {
        this.detail.set(d);
        this.phase.set('ready');
      },
      error: () => this.fail('Nie udało się pobrać szczegółów AED.'),
    });
  }

  private fail(msg: string): void {
    this.message = msg;
    this.phase.set('error');
  }
}
