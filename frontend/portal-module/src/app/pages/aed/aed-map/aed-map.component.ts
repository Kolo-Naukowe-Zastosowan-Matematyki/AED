import { isPlatformBrowser } from '@angular/common';
import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  PLATFORM_ID,
  SimpleChanges,
  ViewChild,
  inject,
} from '@angular/core';
import * as L from 'leaflet';

import { AedFilters, AedPoints, AedService } from '../aed.service';

const COLORS = { open: '#1b7a3d', unknown: '#6c6c6c', closed: '#3d3d3d' };

/**
 * Lekka mapa Leaflet (renderer canvas) – kilkanaście tysięcy punktów bez wtyczek do klastrowania.
 * Ta sama biblioteka i podkład co w portalu (shared/map).
 */
@Component({
  selector: 'aed-map',
  standalone: true,
  template: `<div #host class="aed-map" [style.height]="height" role="region" [attr.aria-label]="label"></div>`,
  styles: [
    `
      :host { display: block; }
      .aed-map { width: 100%; border-radius: 4px; background: #eef1f4; z-index: 0; }
      :host ::ng-deep .aed-user { background: #0865c9; border: 3px solid #fff; border-radius: 50%;
        box-shadow: 0 0 0 2px #0865c9, 0 0 14px rgba(8, 101, 201, 0.7); }
      :host ::ng-deep .aed-target { background: #d40043; border: 3px solid #fff; border-radius: 50%;
        box-shadow: 0 0 0 3px #d40043; }
      :host ::ng-deep .aed-pick { background: #ffc605; border: 3px solid #0f2648; border-radius: 50%; }
    `,
  ],
})
export class AedMapComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('host', { static: true }) host!: ElementRef<HTMLDivElement>;
  @Input() data: AedPoints | null = null;
  @Input() filters: AedFilters | null = null;
  @Input() user: [number, number] | null = null;
  @Input() target: number | null = null; // indeks wybranego AED
  @Input() pick: [number, number] | null = null; // punkt wskazany w formularzu zgłoszenia
  @Input() height = '60vh';
  @Input() interactiveMarkers = true;
  @Input() label = 'Mapa defibrylatorów AED. Te same informacje są dostępne jako lista.';
  @Output() selectAed = new EventEmitter<number>();
  @Output() mapClick = new EventEmitter<[number, number]>();

  private readonly aed = inject(AedService);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));
  private map?: L.Map;
  private layer?: L.LayerGroup;
  private extras?: L.LayerGroup;
  private renderer?: L.Canvas;
  private fitted = false;

  ngAfterViewInit(): void {
    if (!this.isBrowser) return;
    this.map = L.map(this.host.nativeElement, { preferCanvas: true, zoomControl: true }).setView([52.07, 19.48], 6);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">współtwórcy OpenStreetMap</a>',
    }).addTo(this.map);
    this.renderer = L.canvas({ padding: 0.3 });
    this.extras = L.layerGroup().addTo(this.map);
    this.map.on('click', (e: L.LeafletMouseEvent) => this.mapClick.emit([e.latlng.lat, e.latlng.lng]));
    this.drawPoints();
    this.drawExtras();
  }

  ngOnChanges(ch: SimpleChanges): void {
    if (!this.map) return;
    if (ch['data'] || ch['filters']) this.drawPoints();
    if (ch['user'] || ch['target'] || ch['pick']) this.drawExtras();
  }

  ngOnDestroy(): void {
    this.map?.remove();
  }

  invalidate(): void {
    setTimeout(() => this.map?.invalidateSize(), 0);
  }

  private drawPoints(): void {
    if (!this.map || !this.data) return;
    this.layer?.remove();
    const data = this.data;
    const markers: L.Layer[] = [];
    data.points.forEach((p, i) => {
      if (this.filters && !this.aed.passes(data, p, this.filters)) return;
      const st = this.aed.status(data, p);
      const m = L.circleMarker([p[0], p[1]], {
        renderer: this.renderer,
        radius: st === 'open' ? 6 : 5,
        weight: st === 'closed' ? 2 : 1.5,
        color: st === 'closed' ? COLORS.closed : '#fff',
        fillColor: st === 'closed' ? '#fff' : COLORS[st],
        fillOpacity: 1,
        interactive: this.interactiveMarkers,
      });
      if (this.interactiveMarkers) m.on('click', () => this.selectAed.emit(i));
      markers.push(m);
    });
    this.layer = L.layerGroup(markers).addTo(this.map);
  }

  private drawExtras(): void {
    if (!this.map || !this.extras) return;
    this.extras.clearLayers();
    const pts: L.LatLngExpression[] = [];
    if (this.user) {
      L.marker(this.user, { icon: L.divIcon({ className: 'aed-user', iconSize: [18, 18] }), keyboard: false, interactive: false })
        .addTo(this.extras);
      pts.push(this.user);
    }
    if (this.data && this.target !== null && this.data.points[this.target]) {
      const p = this.data.points[this.target];
      L.marker([p[0], p[1]], { icon: L.divIcon({ className: 'aed-target', iconSize: [22, 22] }), keyboard: false, interactive: false })
        .addTo(this.extras);
      if (this.user) {
        L.polyline([this.user, [p[0], p[1]]], { color: '#d40043', weight: 4, dashArray: '8 8', interactive: false }).addTo(this.extras);
      }
      pts.push([p[0], p[1]]);
    }
    if (this.pick) {
      L.marker(this.pick, { icon: L.divIcon({ className: 'aed-pick', iconSize: [20, 20] }), keyboard: false, interactive: false })
        .addTo(this.extras);
      if (!this.fitted) this.map.setView(this.pick, 17);
    }
    if (pts.length === 2) {
      this.map.fitBounds(L.latLngBounds(pts).pad(0.4), { maxZoom: 18 });
    } else if (pts.length === 1 && !this.pick) {
      this.map.setView(pts[0], 16);
    }
  }
}
