/**
 * Geokodowanie adresu przez Nominatim (OSM), tak jak w portalu (services/nominatim-geocode.service.ts).
 * Wywoływane tylko na żądanie użytkownika (zasady usługi: max 1 zapytanie/s, bez autouzupełniania).
 * Używamy fetch zamiast HttpClient, żeby interceptory portalu nie dodawały nagłówków do zewnętrznej usługi.
 */
export async function geocodeAddress(q: string): Promise<{ lat: number; lon: number; label: string } | null> {
  const url =
    'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=pl&accept-language=pl&q=' +
    encodeURIComponent(q.trim());
  try {
    const r = await fetch(url, { headers: { Accept: 'application/json' } });
    const j = await r.json();
    return j[0] ? { lat: +j[0].lat, lon: +j[0].lon, label: j[0].display_name } : null;
  } catch {
    return null;
  }
}
