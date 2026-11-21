import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LocalizeRouterPipe } from '@gilsdav/ngx-translate-router';

import { SeoService } from '@app/services/seo.service';
import { AedService, AedStats } from '../aed.service';

/** Strona startowa modułu: najpierw dwie akcje ratunkowe, dopiero potem reszta. */
@Component({
  selector: 'app-aed-start',
  standalone: true,
  imports: [RouterLink, LocalizeRouterPipe],
  templateUrl: './aed-start.component.html',
  styleUrls: ['../aed.scss', './aed-start.component.scss'],
})
export class AedStartComponent implements OnInit {
  private readonly aed = inject(AedService);
  private readonly seo = inject(SeoService);
  readonly stats = signal<AedStats | null>(null);

  n(v: number): string {
    return (v ?? 0).toLocaleString('pl-PL');
  }

  ngOnInit(): void {
    this.seo.setPageTitle(['Mapa AED']);
    this.aed.stats().subscribe({ next: (s) => this.stats.set(s), error: () => this.stats.set(null) });
  }
}
