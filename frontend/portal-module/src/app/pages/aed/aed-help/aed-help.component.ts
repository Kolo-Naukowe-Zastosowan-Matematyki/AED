import { Component, OnInit, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LocalizeRouterPipe } from '@gilsdav/ngx-translate-router';

import { SeoService } from '@app/services/seo.service';
import { AedFirstAidComponent } from '../aed-first-aid/aed-first-aid.component';

@Component({
  selector: 'app-aed-help',
  standalone: true,
  imports: [AedFirstAidComponent, RouterLink, LocalizeRouterPipe],
  template: `
    <div class="container help">
      <h1 class="help__title">Jak udzielić pomocy</h1>
      <p class="aed-lead">Gdy ktoś nagle upada, nie reaguje i nie oddycha prawidłowo:</p>
      <aed-first-aid></aed-first-aid>
      <p class="help__cta">
        <a class="aed-btn aed-btn--sos aed-btn--xl" [routerLink]="['/!aed', '!teraz'] | localize">Znajdź najbliższy AED</a>
      </p>
    </div>
  `,
  styleUrls: ['../aed.scss'],
  styles: [
    `
      .help { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 760px; }
      .help__title { font-size: 1.9rem; }
      .help__cta { margin-top: 1.5rem; }
    `,
  ],
})
export class AedHelpComponent implements OnInit {
  private readonly seo = inject(SeoService);
  ngOnInit(): void {
    this.seo.setPageTitle(['Jak udzielić pomocy', 'Mapa AED']);
  }
}
