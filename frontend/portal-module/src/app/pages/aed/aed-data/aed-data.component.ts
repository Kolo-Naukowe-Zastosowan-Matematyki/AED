import { KeyValuePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';

import { SeoService } from '@app/services/seo.service';
import { AedService } from '../aed.service';

/** Źródła danych, eksport zbioru we wzorcowym zakresie, instrukcja dla dysponentów. */
@Component({
  selector: 'app-aed-data',
  standalone: true,
  imports: [KeyValuePipe],
  templateUrl: './aed-data.component.html',
  styleUrls: ['../aed.scss', './aed-data.component.scss'],
})
export class AedDataComponent implements OnInit, OnDestroy {
  private readonly aed = inject(AedService);
  private readonly seo = inject(SeoService);
  readonly sources = signal<any | null>(null);
  readonly refreshing = signal(false);
  private timer?: ReturnType<typeof setTimeout>;

  ngOnInit(): void {
    this.seo.setPageTitle(['Dane i źródła', 'Mapa AED']);
    this.load();
  }

  ngOnDestroy(): void {
    clearTimeout(this.timer);
  }

  load(): void {
    this.aed.sources().subscribe((s) => {
      this.sources.set(s);
      const busy = String(s?.danegov?.stan || '').startsWith('pobieranie');
      this.refreshing.set(busy);
      if (busy) this.timer = setTimeout(() => this.load(), 2000);
      else this.aed.points(true);
    });
  }

  refresh(): void {
    this.refreshing.set(true);
    this.aed.refresh().subscribe(() => this.load());
  }

  num(v: number): string {
    return (v ?? 0).toLocaleString('pl-PL');
  }

  order = (): number => 0;
}
