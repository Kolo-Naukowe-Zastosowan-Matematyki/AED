import { Component, Input, OnDestroy, signal } from '@angular/core';

/**
 * Instrukcja pierwszej pomocy + metronom 110/min. Używana na stronie „Jak pomóc”
 * oraz w trybie awaryjnym (wersja kompaktowa).
 * Treść do weryfikacji z aktualnymi wytycznymi ERC / Polskiej Rady Resuscytacji.
 */
@Component({
  selector: 'aed-first-aid',
  standalone: true,
  templateUrl: './aed-first-aid.component.html',
  styleUrls: ['../aed.scss', './aed-first-aid.component.scss'],
})
export class AedFirstAidComponent implements OnDestroy {
  @Input() compact = false;
  readonly running = signal(false);
  readonly beat = signal(false);
  private timer?: ReturnType<typeof setInterval>;
  private audio?: AudioContext;

  toggle(): void {
    if (this.running()) {
      clearInterval(this.timer);
      this.running.set(false);
      return;
    }
    const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
    this.audio = this.audio || (Ctx ? new Ctx() : undefined);
    const tick = () => {
      if (this.audio) {
        const o = this.audio.createOscillator();
        const g = this.audio.createGain();
        o.frequency.value = 880;
        g.gain.setValueAtTime(0.3, this.audio.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, this.audio.currentTime + 0.08);
        o.connect(g).connect(this.audio.destination);
        o.start();
        o.stop(this.audio.currentTime + 0.09);
      }
      this.beat.set(true);
      setTimeout(() => this.beat.set(false), 110);
    };
    tick();
    this.timer = setInterval(tick, 60000 / 110);
    this.running.set(true);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
    this.audio?.close();
  }
}
