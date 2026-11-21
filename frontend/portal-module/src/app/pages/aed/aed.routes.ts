import { Route } from '@angular/router';

import { AedBrowseComponent } from './aed-browse/aed-browse.component';
import { AedDataComponent } from './aed-data/aed-data.component';
import { AedEmergencyComponent } from './aed-emergency/aed-emergency.component';
import { AedHelpComponent } from './aed-help/aed-help.component';
import { AedReportComponent } from './aed-report/aed-report.component';
import { AedStartComponent } from './aed-start/aed-start.component';

/** Moduł „Mapa AED”: /pl/aed, /pl/aed/teraz, /pl/aed/mapa, /pl/aed/pomoc, /pl/aed/zglos, /pl/aed/dane */
export const AED_ROUTES: Route[] = [
  { path: '', component: AedStartComponent },
  { path: '!teraz', component: AedEmergencyComponent, data: { breadcrumbs: { translationKey: 'Aed.Emergency' } } },
  { path: '!mapa', component: AedBrowseComponent, data: { breadcrumbs: { translationKey: 'Aed.Browse' } } },
  { path: '!pomoc', component: AedHelpComponent, data: { breadcrumbs: { translationKey: 'Aed.Help' } } },
  { path: '!zglos', component: AedReportComponent, data: { breadcrumbs: { translationKey: 'Aed.Report' } } },
  { path: '!dane', component: AedDataComponent, data: { breadcrumbs: { translationKey: 'Aed.Data' } } },
];
