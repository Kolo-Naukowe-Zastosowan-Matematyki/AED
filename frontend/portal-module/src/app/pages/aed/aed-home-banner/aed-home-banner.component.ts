import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LocalizeRouterPipe } from '@gilsdav/ngx-translate-router';

/** Baner akcji AED na stronie głównej portalu (wstawiany pod sekcją hero). */
@Component({
  selector: 'home-aed-banner',
  standalone: true,
  imports: [RouterLink, LocalizeRouterPipe],
  template: `
    <section class="aed-banner" aria-labelledby="aed-banner-title">
      <div class="container aed-banner__inner">
        <div class="aed-banner__text">
          <h2 id="aed-banner-title">Mapa AED – dane na ratunek</h2>
          <p>Znajdź najbliższy defibrylator w kilka sekund. Twoja instytucja ma AED? Udostępnij dane w dane.gov.pl.</p>
        </div>
        <div class="aed-banner__actions">
          <a class="aed-banner__sos" [routerLink]="['/!aed', '!teraz'] | localize">Znajdź AED teraz</a>
          <a class="aed-banner__more" [routerLink]="['/!aed'] | localize">O module AED</a>
        </div>
      </div>
    </section>
  `,
  styles: [
    `
      .aed-banner { background: #0f2648; color: #fff; padding: 1.2rem 0; margin-bottom: 2rem; }
      .aed-banner__inner { display: flex; flex-wrap: wrap; gap: 1rem 2rem; align-items: center; justify-content: space-between; }
      .aed-banner h2 { color: #fff; font-size: 1.4rem; margin: 0 0 0.25rem; }
      .aed-banner p { margin: 0; }
      .aed-banner__actions { display: flex; flex-wrap: wrap; gap: 0.6rem; }
      .aed-banner a { display: inline-flex; align-items: center; min-height: 48px; padding: 0.6rem 1.2rem;
        border-radius: 4px; font-weight: 700; text-decoration: none; }
      .aed-banner a:focus-visible { outline: 4px solid #ffc605; outline-offset: 2px; }
      .aed-banner__sos { background: #d40043; color: #fff; }
      .aed-banner__sos:hover { background: #a91e2c; color: #fff; }
      .aed-banner__more { border: 2px solid #fff; color: #fff; }
      .aed-banner__more:hover { background: rgba(255, 255, 255, 0.15); color: #fff; }
      :host-context(body.black-yellow) .aed-banner,
      :host-context(body.black-white) .aed-banner,
      :host-context(body.yellow-black) .aed-banner { background: transparent; color: inherit; border: 2px solid currentColor; }
    `,
  ],
})
export class AedHomeBannerComponent {}
