import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { SeoService } from '@app/services/seo.service';
import { AedMapComponent } from '../aed-map/aed-map.component';
import { AedPoints, AedService } from '../aed.service';

interface PhotoVerdict {
  ocena: 'prawdopodobnie_aed' | 'niepewne' | 'odrzuc' | 'brak_weryfikacji';
  wynik?: number;
  uwagi?: string[];
  zdjecie_id?: string;
  exif?: { gps?: [number, number]; data_wykonania?: string };
}

/** Zgłoszenie AED przez mieszkańca: zdjęcie (wstępna weryfikacja – strefa 4), miejsce na mapie, opis. */
@Component({
  selector: 'app-aed-report',
  standalone: true,
  imports: [FormsModule, AedMapComponent],
  templateUrl: './aed-report.component.html',
  styleUrls: ['../aed.scss', './aed-report.component.scss'],
})
export class AedReportComponent implements OnInit {
  private readonly aed = inject(AedService);
  private readonly seo = inject(SeoService);

  readonly data = signal<AedPoints | null>(null);
  readonly pick = signal<[number, number] | null>(null);
  readonly preview = signal<string | null>(null);
  readonly verdict = signal<PhotoVerdict | null>(null);
  readonly checking = signal(false);
  readonly sent = signal<{ id: string } | null>(null);
  readonly error = signal('');

  form = { nazwa_obiektu: '', opis_lokalizacji: '', godziny: 'nie_wiem', godziny_tekst: '', dostep: 'nieznany', wewnatrz: '' };
  private file?: File;

  ngOnInit(): void {
    this.seo.setPageTitle(['Zgłoś AED', 'Mapa AED']);
    this.aed.points().subscribe((d) => this.data.set(d));
  }

  onFile(ev: Event): void {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (!f) return;
    this.file = f;
    this.preview.set(URL.createObjectURL(f));
    this.verify();
  }

  verify(): void {
    if (!this.file) return;
    const p = this.pick();
    this.checking.set(true);
    this.aed.verifyPhoto(this.file, p?.[0], p?.[1]).subscribe({
      next: (v: PhotoVerdict) => {
        this.checking.set(false);
        this.verdict.set(v);
        if (!this.pick() && v.exif?.gps) this.pick.set(v.exif.gps); // miejsce z GPS zdjęcia jako podpowiedź
      },
      error: () => {
        this.checking.set(false);
        this.verdict.set({ ocena: 'brak_weryfikacji', uwagi: ['Nie udało się sprawdzić zdjęcia. Możesz wysłać zgłoszenie bez oceny.'] });
      },
    });
  }

  useMyLocation(): void {
    navigator.geolocation?.getCurrentPosition(
      (p) => this.pick.set([p.coords.latitude, p.coords.longitude]),
      () => this.error.set('Nie udało się ustalić lokalizacji. Kliknij miejsce na mapie.'),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  }

  submit(): void {
    this.error.set('');
    const p = this.pick();
    if (!p) return this.error.set('Wskaż na mapie, gdzie jest AED.');
    if (!this.form.opis_lokalizacji.trim()) return this.error.set('Opisz, gdzie dokładnie wisi AED.');
    const hours = this.form.godziny === '24/7' ? '24/7' : this.form.godziny === 'tekst' ? this.form.godziny_tekst : '';
    this.aed
      .submit({
        szerokosc: p[0],
        dlugosc: p[1],
        nazwa_obiektu: this.form.nazwa_obiektu,
        opis_lokalizacji: this.form.opis_lokalizacji,
        godziny_dostepnosci: hours,
        dostep: this.form.dostep,
        wewnatrz: this.form.wewnatrz === '' ? null : this.form.wewnatrz === 'tak',
        zdjecie_id: this.verdict()?.zdjecie_id ?? null,
      })
      .subscribe({
        next: (r: any) => this.sent.set({ id: r.id }),
        error: (e) => this.error.set(e?.error?.blad || 'Nie udało się wysłać zgłoszenia.'),
      });
  }

  verdictText(v: PhotoVerdict): string {
    switch (v.ocena) {
      case 'prawdopodobnie_aed':
        return 'Na zdjęciu widać oznaczenie AED.';
      case 'niepewne':
        return 'Nie mamy pewności, czy na zdjęciu jest AED.';
      case 'odrzuc':
        return 'Tego zdjęcia nie możemy przyjąć.';
      default:
        return 'Zdjęcie nie zostało ocenione automatycznie.';
    }
  }
}
