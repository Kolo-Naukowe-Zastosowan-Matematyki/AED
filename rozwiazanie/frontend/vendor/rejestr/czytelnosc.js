(() => {
  const root = document.documentElement;
  const header = document.querySelector(".topbar");
  const toolbar = header.querySelector(".reading-tools");
  const themeNames = {standard: "Kolory domyślne", white: "Biały tekst na czarnym tle",
    yellow: "Żółty tekst na czarnym tle", black: "Czarny tekst na żółtym tle"};
  const scales = ["100", "115", "130", "150"];
  function read(key, fallback) {
    try { return localStorage.getItem("aed." + key) || fallback; } catch { return fallback; }
  }
  function choose(key, value, save) {
    root.dataset[key] = value;
    toolbar.querySelectorAll("button[data-" + key + "]").forEach(button =>
      button.setAttribute("aria-pressed", String(button.dataset[key] === value)));
    if (save) try { localStorage.setItem("aed." + key, value); } catch {}
  }
  function group(key, label, options) {
    const group = document.createElement("div");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", label);
    for (const [value, name, text] of options) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset[key] = value;
      button.title = name;
      button.setAttribute("aria-label", name);
      button.textContent = text;
      button.onclick = () => choose(key, value, true);
      group.append(button);
    }
    toolbar.append(group);
    const stored = read(key, options[0][0]);
    choose(key, options.some(([v]) => v === stored) ? stored : options[0][0], false);
  }
  group("contrast", "Kontrast strony", Object.entries(themeNames).map(([v, name]) => [v, name, "A"]));
  group("textsize", "Rozmiar tekstu", scales.map((v, i) => [v, "Rozmiar tekstu " + v + "%", "A" + "+".repeat(i)]));
  const toggle = header.querySelector(".reading-toggle");
  function expand(open) {
    toggle.setAttribute("aria-expanded", String(open));
    toolbar.classList.toggle("expanded", open);
  }
  toggle.onclick = () => expand(toggle.getAttribute("aria-expanded") !== "true");
  header.addEventListener("keydown", e => {
    if (e.key === "Escape" && toggle.offsetWidth && toolbar.classList.contains("expanded")) {
      expand(false); toggle.focus();
    }
  });
  new ResizeObserver(() => root.style.setProperty("--header-height", header.offsetHeight + "px")).observe(header);
})();
