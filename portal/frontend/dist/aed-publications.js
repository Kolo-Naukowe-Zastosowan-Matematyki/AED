const levels = {
  region: {label: "Województwa", fields: ["region"]},
  powiat: {label: "Powiaty", fields: ["region", "powiat"]},
  gmina: {label: "Gminy", fields: ["region", "powiat", "gmina"]},
};
const dates = new Intl.DateTimeFormat("pl-PL", {
  dateStyle: "medium", timeStyle: "medium", timeZone: "Europe/Warsaw"
});

function element(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

function selector(label, options, onChange) {
  const wrapper = element("label", label + " ");
  const select = element("select");
  select.className = "form-control";
  for (const [value, text] of options) select.add(new Option(text, value));
  select.addEventListener("change", () => onChange(select.value));
  wrapper.append(select);
  return wrapper;
}

function table(headers) {
  const grid = element("table");
  grid.className = "table";
  const row = grid.createTHead().insertRow();
  for (const title of headers) {
    const th = element("th", title);
    th.scope = "col";
    row.append(th);
  }
  grid.createTBody();
  return grid;
}

class AedRegistryCharts extends HTMLElement {
  set resourceId(id) { this.setAttribute("resource-id", id); }
  static get observedAttributes() { return ["resource-id"]; }
  attributeChangedCallback() { if (this.isConnected) this.load(); }
  connectedCallback() { if (this.hasAttribute("resource-id")) this.load(); }
  disconnectedCallback() { this.request?.abort(); }

  async load() {
    this.request?.abort();
    const request = this.request = new AbortController();
    this.textContent = "Wczytywanie statystyk wykazu…";
    try {
      const id = this.getAttribute("resource-id").split(",")[0];
      const response = await fetch("/aed-api/wykresy/" + encodeURIComponent(id), {signal: request.signal});
      if (!response.ok) throw new Error();
      this.data = await response.json();
      this.showPanel();
    } catch (error) {
      if (request.signal.aborted) return;
      const retry = element("button", "Spróbuj ponownie");
      retry.className = "btn btn-outline-primary";
      retry.onclick = () => this.load();
      this.replaceChildren(element("p", "Nie udało się wczytać statystyk wykazu."), retry);
    }
  }

  showPanel() {
    this.level = "region";
    const content = element("div");
    const pickLevel = selector("Podział administracyjny", Object.entries(levels).map(
      ([value, item]) => [value, item.label]), level => {
      this.level = level;
      this.geography(content);
    });
    const pickView = selector("Widok", [["geo", "Rozmieszczenie AED"], ["history", "Historia wykazu"]], value => {
      pickLevel.hidden = value !== "geo";
      if (value === "geo") this.geography(content);
      else this.history(content);
    });
    const controls = element("div");
    controls.className = "d-flex flex-wrap align-items-end";
    pickView.className = "mr-3";
    controls.append(pickView, pickLevel);
    this.replaceChildren(controls, content);
    this.geography(content);
  }

  geography(content) {
    const keys = levels[this.level].fields;
    const counts = new Map();
    for (const area of this.data.areas) {
      const key = JSON.stringify(keys.map(field => area[field]));
      counts.set(key, (counts.get(key) || 0) + area.count);
    }
    const rows = Array.from(counts, ([key, count]) => {
      const path = JSON.parse(key);
      const name = path.pop() || "Obszar nieustalony";
      return {label: [name, ...path.reverse().filter(Boolean)].join(" · "), count};
    }).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "pl"));
    const grid = table(["Obszar", "Liczba AED"]);
    for (const row of rows) {
      const cells = grid.tBodies[0].insertRow();
      cells.insertCell().textContent = row.label;
      const value = cells.insertCell();
      const bar = element("meter");
      bar.min = 0;
      bar.max = rows[0].count;
      bar.value = row.count;
      bar.style.width = "min(24vw, 20rem)";
      bar.setAttribute("aria-hidden", "true");
      value.append(bar, document.createTextNode(" " + row.count));
    }
    const heading = element("h2", "Liczba AED według obszaru");
    const summary = element("p", "Cały wykaz: " + this.data.total + " AED.");
    content.replaceChildren(heading, summary, grid);
    if (this.level !== "region") content.append(element("p", "Przypisanie do powiatu i gminy opiera się na miejscowości i województwie w słowniku TERYT."));
  }

  history(content) {
    const history = this.data.history;
    const heading = element("h2", "Liczba AED w kolejnych publikacjach");
    content.replaceChildren(heading);
    if (history.length === 1) content.append(element("p", "To pierwszy zapisany stan wykazu. Kolejne zmiany pojawią się po publikacji."));
    if (history.length > 1) content.append(historyPlot(history));
    const grid = table(["Data pomiaru", "Liczba AED", "Zmiana"]);
    history.forEach((point, index) => {
      const row = grid.tBodies[0].insertRow();
      row.insertCell().textContent = dates.format(new Date(point.recorded_at));
      row.insertCell().textContent = point.total;
      const delta = index ? point.total - history[index - 1].total : 0;
      row.insertCell().textContent = index ? (delta > 0 ? "+" : "") + delta : "Pierwszy pomiar";
    });
    content.append(grid);
  }
}

function historyPlot(history) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 780 180");
  svg.style.width = "100%";
  svg.style.maxHeight = "16rem";
  svg.setAttribute("aria-hidden", "true");
  const first = Date.parse(history[0].recorded_at);
  const span = Math.max(1, Date.parse(history[history.length - 1].recorded_at) - first);
  const peak = history.reduce((max, p) => Math.max(max, p.total), 1);
  let path = "";
  history.forEach((p, i) => {
    const x = 40 + (Date.parse(p.recorded_at) - first) / span * 730;
    const y = 150 - p.total / peak * 125;
    path += i ? " H " + x + " V " + y : "M " + x + " " + y;
  });
  const line = document.createElementNS(ns, "path");
  line.setAttribute("d", path);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "currentColor");
  line.setAttribute("stroke-width", "3");
  svg.append(line);
  for (const [x, y, text, anchor] of [[34, 30, peak, "end"], [34, 154, 0, "end"],
    [40, 175, dates.format(first), "start"], [770, 175, dates.format(first + span), "end"]]) {
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", x); label.setAttribute("y", y);
    label.setAttribute("fill", "currentColor"); label.setAttribute("text-anchor", anchor);
    label.textContent = text; svg.append(label);
  }
  return svg;
}
customElements.define("aed-registry-charts", AedRegistryCharts);

