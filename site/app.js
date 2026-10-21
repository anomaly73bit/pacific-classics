// Pacific Classics — front end (vanilla JS, no build step)
(() => {
  const SOURCE_NAMES = { autoscout24: "AutoScout24", sauto: "Sauto.cz", willhaben: "willhaben", kleinanzeigen: "Kleinanzeigen", mobilede: "mobile.de",
    autobazar: "Autobazar.eu", marktplaats: "Marktplaats", "2dehands": "2dehands", classictrader: "Classic Trader" };
  const COUNTRY_IT = { DE: "Germania", AT: "Austria", CZ: "Repubblica Ceca", SK: "Slovacchia", HU: "Ungheria", IT: "Italia", FR: "Francia", BE: "Belgio", NL: "Paesi Bassi", ES: "Spagna", LU: "Lussemburgo", CH: "Svizzera", PL: "Polonia", SE: "Svezia" };
  const COUNTRY_EN = { DE: "Germany", AT: "Austria", CZ: "Czechia", SK: "Slovakia", HU: "Hungary", IT: "Italy", FR: "France", BE: "Belgium", NL: "Netherlands", ES: "Spain", LU: "Luxembourg", CH: "Switzerland", PL: "Poland", SE: "Sweden" };
  const COUNTRY = new Proxy({}, { get: (_, k) => (lang === "it" ? COUNTRY_IT : COUNTRY_EN)[k] });

  const RISKY = new Set(["PRICE_SUSPICIOUS", "KW_ACCIDENT", "KW_DEFECT", "KW_NO_PAPERS"]);
  const LEVEL_ORDER = { danger: 0, good: 1, warn: 2, info: 3 };
  const PAGE = 24;

  let lang = pickLang(), T = I18N[lang];
  const mt = (m, k) => (lang === "it" && m.it && m.it[k]) || m[k];   // model text in the current language
  let ALL = [], MODELS = [], MODEL_BY_ID = {}, REPORT = {}, META = {};
  let shown = PAGE;
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = u => /^(https?:)?\/\//.test(u || "") || /^img\//.test(u || "") ? u : "#";
  const flag = cc => cc && cc.length === 2 ? String.fromCodePoint(...[...cc.toUpperCase()].map(c => 127397 + c.charCodeAt(0))) : "";

  function pickLang() {
    try { const s = localStorage.getItem("pc-lang"); if (s) return s; } catch (e) {}
    return "it";
  }

  async function load() {
    const get = p => fetch(p, { cache: "no-store" }).then(r => r.ok ? r.json() : null).catch(() => null);
    const [ls, models, report] = await Promise.all([get("data/listings.json"), get("data/models.json"), get("data/report.json")]);
    ALL = ls?.listings || []; META = ls?.meta || {}; MODELS = models || []; REPORT = report || {};
    MODEL_BY_ID = Object.fromEntries(MODELS.map(m => [m.id, m]));
    fillSelects();
    applyLang();
    readHash();
    render();
  }

  // ---------- i18n
  function applyLang() {
    T = I18N[lang];
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-t]").forEach(el => { const v = T[el.dataset.t]; if (typeof v === "string") el.textContent = v; });
    $("#q").placeholder = T.search;
    $("#lang").textContent = T.lang;
    $("#fModel").options[0].textContent = T.allModels;
    $("#fCountry").options[0].textContent = T.allCountries;
    const demo = $("#demo"); demo.hidden = !META.demo; demo.textContent = T.demoBanner;
    $("#updated").textContent = META.generated ? T.updated(new Date(META.generated).toLocaleString(lang === "it" ? "it-IT" : "en-GB")) : "";
  }

  function fillSelects() {
    const fm = $("#fModel");
    fm.innerHTML = `<option value=""></option>`;
    const byMake = {};
    MODELS.forEach(m => (byMake[m.make] ||= []).push(m));
    Object.keys(byMake).sort().forEach(mk => {
      const g = document.createElement("optgroup"); g.label = mk;
      byMake[mk].forEach(m => { const n = ALL.filter(l => l.model_id === m.id && !l.duplicate_of).length;
        g.insertAdjacentHTML("beforeend", `<option value="${esc(m.id)}">${esc(mt(m, "model"))} ${esc(m.chassis)} (${n})</option>`); });
      fm.appendChild(g);
    });
    const countries = [...new Set(ALL.map(l => l.country).filter(Boolean))].sort();
    $("#fCountry").innerHTML = `<option value=""></option>` + countries.map(c => `<option value="${c}">${flag(c)} ${esc(COUNTRY[c] || c)}</option>`).join("");
  }

  // ---------- filtering
  const F = () => ({
    q: $("#q").value.trim().toLowerCase(), model: $("#fModel").value, seg: $("#fSeg").value, country: $("#fCountry").value,
    pmin: +$("#fPmin").value || 0, pmax: +$("#fPmax").value || Infinity,
    ymin: +$("#fYmin").value || 0, ymax: +$("#fYmax").value || Infinity, km: +$("#fKm").value || Infinity,
    hist: $("#fHist").value, seller: $("#fSeller").value,
    deals: $("#fDeals").checked, safe: $("#fSafe").checked, sort: $("#sort").value,
  });

  function filtered() {
    const f = F();
    const has = (l, c) => l.alerts.some(a => a.code === c);
    let out = ALL.filter(l => {
      if (f.model && l.model_id !== f.model) return false;
      if (f.seg && (MODEL_BY_ID[l.model_id] || {}).segment !== f.seg) return false;
      if (f.country && l.country !== f.country) return false;
      if (l.price_eur != null && (l.price_eur < f.pmin || l.price_eur > f.pmax)) return false;
      if (l.price_eur == null && (f.pmin || f.pmax !== Infinity)) return false;
      if (l.year && (l.year < f.ymin || l.year > f.ymax)) return false;
      if (l.mileage_km && l.mileage_km > f.km) return false;
      if (f.hist === "fiva" && !l.historic?.fiva) return false;
      if (f.hist === "asi" && !l.historic?.asi) return false;
      if (f.seller && l.seller_type !== f.seller) return false;
      if (f.deals && !(has(l, "PRICE_DEAL") || has(l, "PRICE_DROP"))) return false;
      if (f.safe && l.alerts.some(a => RISKY.has(a.code))) return false;
      if (f.q) {
        const m = MODEL_BY_ID[l.model_id] || {};
        const hay = [l.title, l.model_raw, l.city, l.region, COUNTRY[l.country], m.make, m.model, m.chassis].join(" ").toLowerCase();
        if (!f.q.split(/\s+/).every(w => hay.includes(w))) return false;
      }
      return true;
    });
    const by = {
      score: (a, b) => b.score - a.score,
      price_asc: (a, b) => (a.price_eur ?? 9e9) - (b.price_eur ?? 9e9),
      price_desc: (a, b) => (b.price_eur ?? -1) - (a.price_eur ?? -1),
      year: (a, b) => (a.year ?? 9999) - (b.year ?? 9999),
      km: (a, b) => (a.mileage_km ?? 9e9) - (b.mileage_km ?? 9e9),
      new: (a, b) => String(b.first_seen).localeCompare(String(a.first_seen)),
    }[f.sort];
    return out.sort(by);
  }

  // ---------- rendering
  function render() {
    const list = filtered();
    $("#count").textContent = T.results(list.length);
    const grid = $("#grid");
    grid.innerHTML = list.length ? list.slice(0, shown).map(card).join("") : `<div class="empty">${esc(T.noResults)}</div>`;
    $("#more").hidden = list.length <= shown;
    $("#more").textContent = `+ ${Math.min(PAGE, list.length - shown)}`;
    writeHash();
  }

  const alertText = (a, m) => {
    const fn = T.alerts[a.code];
    const p = a.code === "ENGINE_BAD" && m ? { ...a.params, note: mt(m, "engine_bad_note") || "" } : (a.params || {});
    return fn ? fn(p) : a.code;
  };
  const sortAlerts = als => [...als].sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]);
  const mapUrl = l => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([l.zip, l.city, l.region, COUNTRY[l.country] || l.country].filter(Boolean).join(" "))}`;
  const priceHtml = l => l.price_eur != null ? `€ ${fmt(l.price_eur)}` : "—";
  const histBadge = l => l.historic?.fiva ? `<span class="badge hist">FIVA ✓</span>` : l.historic?.asi ? `<span class="badge hist asi">ASI ✓</span>` : "";

  function card(l) {
    const m = MODEL_BY_ID[l.model_id] || {};
    const img = l.images?.[0];
    const keyAlerts = sortAlerts(l.alerts).filter(a => !["DEALER", "PRIVATE", "IMPORT_IT", "HIST_FIVA"].includes(a.code)).slice(0, 4);
    const specs = [l.year, l.mileage_km != null ? `${fmt(l.mileage_km)} km` : null, l.fuel, l.gearbox, l.power_kw ? `${l.power_kw} kW` : null].filter(Boolean);
    return `<article class="card">
      <div class="photo" data-open="${esc(l.id)}">
        ${img ? `<img src="${esc(safeUrl(img))}" alt="${esc(l.title)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.src='img/placeholder.svg'">` : `<img src="img/placeholder.svg" alt="">`}
        <span class="badge score ${l.score >= 75 ? "hi" : ""}" title="${esc(T.score)}">${l.score}</span>
        ${histBadge(l)}
        ${l.images?.length > 1 ? `<span class="badge nph">${esc(T.photos(l.images.length))}</span>` : ""}
      </div>
      <div class="body">
        <div class="top">
          <span class="price">${priceHtml(l)}</span>
          ${l.currency && l.currency !== "EUR" && l.price ? `<span class="orig">${fmt(l.price)} ${esc(l.currency)}</span>` : ""}
        </div>
        <h3 class="title">${esc(l.title)}</h3>
        <span><span class="chip-model">${esc(m.make)} ${esc(mt(m, "model"))} · ${esc(m.chassis)}</span></span>
        <div class="specs">${specs.map(s => `<span>${esc(s)}</span>`).join("")}</div>
        <div class="where">${flag(l.country)} <span>${esc([l.zip, l.city].filter(Boolean).join(" ") || COUNTRY[l.country] || "")}</span>
          · <a href="${mapUrl(l)}" target="_blank" rel="noopener">${esc(T.map)}</a>
          · <span class="src">${esc(SOURCE_NAMES[l.source] || l.source)}${l.seller_type ? " · " + esc(T[l.seller_type]) : ""}</span></div>
        <div class="alerts">${keyAlerts.map(a => `<span class="al ${a.level}">${esc(alertText(a, m))}</span>`).join("")}</div>
        <div class="actions">
          <button class="btn sec" data-open="${esc(l.id)}">${esc(T.details)}</button>
          <a class="btn primary" href="${esc(safeUrl(l.url))}" target="_blank" rel="noopener nofollow">${esc(T.view(SOURCE_NAMES[l.source] || l.source))}</a>
        </div>
      </div>
    </article>`;
  }

  function openDetail(id) {
    const l = ALL.find(x => x.id === id); if (!l) return;
    const m = MODEL_BY_ID[l.model_id] || {};
    const h = l.historic || {}, ref = new Date().getFullYear();
    GALLERY = (l.images?.length ? l.images : ["img/placeholder.svg"]).map(safeUrl);
    const imgs = GALLERY.map((u, i) => `<img src="${esc(u)}" data-gi="${i}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.src='img/placeholder.svg'">`).join("");
    const rows = [
      [T.year, l.year], ["Km", l.mileage_km != null ? fmt(l.mileage_km) : null], [T.fuel, l.fuel], [T.gearbox, l.gearbox],
      [T.country, `${flag(l.country)} ${esc(COUNTRY[l.country] || l.country || "")}`],
      ["📍", `${esc([l.zip, l.city, l.region].filter(Boolean).join(" "))} · <a href="${mapUrl(l)}" target="_blank" rel="noopener">${esc(T.map)}</a>`],
      [T.seller, `${esc(T[l.seller_type] || "–")}${l.seller_name ? " · " + esc(l.seller_name) : ""}`],
      [T.median, REPORT.market?.[l.model_id] ? `€ ${fmt(REPORT.market[l.model_id].median_price)} (${REPORT.market[l.model_id].count})` : "–"],
    ].filter(r => r[1] != null && r[1] !== "");
    $("#dlgBody").innerHTML = `
      <div class="dlg-head"><h2>${priceHtml(l)} · ${esc(l.title)}</h2><button class="x" aria-label="${esc(T.close)}" data-close>×</button></div>
      <div class="gallery">${imgs}</div>
      ${l.images?.length ? `<p class="hint">${esc(T.hoverHint)}</p>` : ""}
      <div class="dlg-grid">
        <div class="panel">
          <h3>${esc(T.details)} · ${esc(T.score)} ${l.score}/100</h3>
          <div class="alerts col">${sortAlerts(l.alerts).map(a => `<span class="al ${a.level}">${esc(alertText(a, m))}</span>`).join("")}</div>
          ${l.description ? `<p class="src" style="margin-top:12px">${esc(l.description)}</p>` : ""}
        </div>
        <div class="panel">
          <dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${typeof v === "number" ? v : v}</dd>`).join("")}</dl>
        </div>
        <div class="panel">
          <h3>${esc(m.make)} ${esc(mt(m, "model"))} (${esc(m.chassis)}) <span class="stars">${"★".repeat(m.reliability || 0)}</span></h3>
          <p><b>${esc(T.strengths)}:</b> ${esc(mt(m, "strengths"))}</p>
          <p><b>${esc(T.engines)}:</b> ${esc(mt(m, "recommended_engines"))}</p>
          <p><b>${esc(T.watchOut)}:</b> ${esc(mt(m, "watch_out"))}</p>
          ${m.engine_bad_note ? `<p><b>⚠</b> ${esc(mt(m, "engine_bad_note"))}</p>` : ""}
        </div>
        <div class="panel">
          <h3>${esc(T.historicBox)}</h3>
          <p>${esc(T.fivaFrom(h.fiva_year ?? "–"))}${h.fiva ? " · <b>" + esc(T.eligibleNow) + "</b>" : ""}</p>
          <p>${esc(T.asiFrom(h.asi_year ?? "–"))}${h.asi ? " · <b>" + esc(T.eligibleNow) + "</b>" : ""}</p>
          ${l.first_seen ? `<p class="src">${esc(T.firstSeen(l.first_seen))}</p>` : ""}
          ${l.also_on?.length ? `<p>${esc(T.alsoOn)}: ${l.also_on.map(o => `<a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">${esc(SOURCE_NAMES[o.source] || o.source)}</a>`).join(", ")}</p>` : ""}
          <p style="margin-top:12px"><a class="btn primary" style="display:inline-block" href="${esc(safeUrl(l.url))}" target="_blank" rel="noopener nofollow">${esc(T.view(SOURCE_NAMES[l.source] || l.source))}</a></p>
        </div>
      </div>`;
    $("#dlg").showModal();
  }

  function renderModels() {
    $("#modelGrid").innerHTML = MODELS.map(m => {
      const n = ALL.filter(l => l.model_id === m.id && !l.duplicate_of).length;
      const elig = ref => m.years[0] + 30 <= ref ? (m.years[1] + 30 <= ref ? "✓ FIVA" : `FIVA ${m.years[0]}–${ref - 30}`) : `FIVA ${m.years[0] + 30}`;
      return `<div class="mcard">
        <h3>${esc(m.make)} ${esc(mt(m, "model"))}</h3>
        <div class="meta">${esc(m.chassis)} · ${m.years[0]}–${m.years[1]} · ${esc(mt(m, "category"))} · <span class="stars">${"★".repeat(m.reliability)}</span></div>
        <p><b>${esc(T.engines)}:</b> ${esc(mt(m, "recommended_engines"))}</p>
        <p><b>${esc(T.strengths)}:</b> ${esc(mt(m, "strengths"))}</p>
        <p><b>${esc(T.watchOut)}:</b> ${esc(mt(m, "watch_out"))}</p>
        <p><b>${esc(T.historicBox)}:</b> ${esc(elig(new Date().getFullYear()))} · ASI ${m.years[0] + 20}</p>
        <button class="count-link" data-model="${esc(m.id)}">${esc(T.results(n))} →</button>
      </div>`;
    }).join("");
  }

  function renderStatus() {
    const s = REPORT.sources || {};
    const rows = Object.entries(s).map(([k, v]) => `<tr><td>${esc(v.name || k)}</td>
      <td><span class="pill ${esc(v.status)}">${esc(v.status)}</span></td><td>${v.fetched ?? 0}</td>
      <td>${esc(v.note || "")}${v.errors?.length ? `<br><small>${v.errors.slice(0, 5).map(esc).join("<br>")}</small>` : ""}</td></tr>`).join("");
    $("#statusBox").innerHTML = `<table class="st"><tr><th>${esc(T.stSource)}</th><th>${esc(T.stStatus)}</th><th>${esc(T.stFetched)}</th><th>${esc(T.stNote)}</th></tr>${rows || `<tr><td colspan="4">${esc(REPORT.note || "–")}</td></tr>`}</table>
      <p class="count">${esc(T.published(REPORT.published ?? ALL.length))}${REPORT.dropped ? " · " + Object.entries(REPORT.dropped).map(([k, v]) => `${k}: ${v}`).join(" · ") : ""}${REPORT.fx_source ? " · FX: " + esc(REPORT.fx_source) : ""}</p>`;
  }

  function showView(v) {
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === v));
    document.querySelectorAll(".view").forEach(s => s.hidden = s.id !== "view-" + v);
    if (v === "models") renderModels();
    if (v === "status") renderStatus();
  }

  // ---------- photos: big preview on hover, full-screen lightbox on click
  let GALLERY = [], lbIndex = 0, peekTimer;
  const peek = $("#peek"), lb = $("#lightbox");
  function showPeek(img) {
    const i = +img.dataset.gi, r = img.getBoundingClientRect(), vw = innerWidth, vh = innerHeight;
    const below = vh - r.bottom - 24, above = r.top - 24;
    const h = Math.max(below, above), w = Math.min(vw - 32, h * 1.5, 900);
    peek.style.width = w + "px"; peek.style.height = Math.min(h, w / 1.33) + "px";
    peek.style.left = Math.max(16, Math.min(vw - w - 16, r.left + r.width / 2 - w / 2)) + "px";
    peek.style.top = (below >= above ? r.bottom + 12 : Math.max(12, r.top - 12 - Math.min(h, w / 1.33))) + "px";
    peek.firstElementChild.src = GALLERY[i];
    peek.hidden = false;
  }
  function hidePeek() { clearTimeout(peekTimer); peek.hidden = true; }
  function openLightbox(i) {
    hidePeek(); lbIndex = (i + GALLERY.length) % GALLERY.length;
    lb.querySelector("img").src = GALLERY[lbIndex];
    lb.querySelector(".lb-count").textContent = `${lbIndex + 1} / ${GALLERY.length}`;
    lb.querySelectorAll(".lb-nav").forEach(b => b.hidden = GALLERY.length < 2);
    lb.hidden = false;
  }
  const hoverCapable = matchMedia("(hover: hover)").matches;
  document.addEventListener("mouseover", e => {
    const img = e.target.closest(".gallery img");
    if (!img || !hoverCapable) return;
    clearTimeout(peekTimer); peekTimer = setTimeout(() => showPeek(img), 120);
  });
  document.addEventListener("mouseout", e => { if (e.target.closest(".gallery img")) hidePeek(); });
  lb.addEventListener("click", e => {
    const a = e.target.closest("[data-lb]")?.dataset.lb;
    if (a === "prev") return openLightbox(lbIndex - 1);
    if (a === "next") return openLightbox(lbIndex + 1);
    if (a === "close" || e.target === lb) lb.hidden = true;
  });
  document.addEventListener("keydown", e => {
    if (lb.hidden) return;
    if (e.key === "ArrowLeft") openLightbox(lbIndex - 1);
    if (e.key === "ArrowRight") openLightbox(lbIndex + 1);
    if (e.key === "Escape") { e.preventDefault(); lb.hidden = true; }
  }, true);
  $("#dlg").addEventListener("close", hidePeek);

  // ---------- URL state (shareable searches)
  const HASH_KEYS = { q: "#q", seg: "#fSeg", model: "#fModel", country: "#fCountry", pmin: "#fPmin", pmax: "#fPmax", ymin: "#fYmin", ymax: "#fYmax", km: "#fKm", hist: "#fHist", seller: "#fSeller", sort: "#sort" };
  function writeHash() {
    const p = new URLSearchParams();
    for (const [k, sel] of Object.entries(HASH_KEYS)) { const v = $(sel).value; if (v && !(k === "sort" && v === "score")) p.set(k, v); }
    if ($("#fDeals").checked) p.set("deals", "1");
    history.replaceState(null, "", p.toString() ? "#" + p : location.pathname);
  }
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    for (const [k, sel] of Object.entries(HASH_KEYS)) if (p.has(k)) $(sel).value = p.get(k);
    $("#fDeals").checked = p.get("deals") === "1";
  }

  // ---------- events
  let t;
  const rerender = () => { shown = PAGE; clearTimeout(t); t = setTimeout(render, 120); };
  document.querySelectorAll("#filters input, #filters select, #q, #sort").forEach(el => el.addEventListener("input", rerender));
  $("#reset").onclick = () => { document.querySelectorAll("#filters input[type=number], #q").forEach(i => i.value = ""); ["#fModel", "#fSeg", "#fCountry", "#fHist", "#fSeller"].forEach(s => $(s).value = ""); $("#fDeals").checked = false; $("#fSafe").checked = true; rerender(); };
  $("#more").onclick = () => { shown += PAGE; render(); };
  $("#toggleFilters").onclick = () => $("#filters").classList.toggle("open");
  $("#lang").onclick = () => { lang = lang === "it" ? "en" : "it"; try { localStorage.setItem("pc-lang", lang); } catch (e) {} applyLang(); render(); const v = document.querySelector(".tab.active").dataset.view; if (v !== "listings") showView(v); };
  document.querySelectorAll(".tab").forEach(b => b.onclick = () => showView(b.dataset.view));
  document.addEventListener("click", e => {
    const gi = e.target.closest(".gallery img"); if (gi) return openLightbox(+gi.dataset.gi);
    const o = e.target.closest("[data-open]"); if (o) return openDetail(o.dataset.open);
    if (e.target.closest("[data-close]")) return $("#dlg").close();
    const mm = e.target.closest("[data-model]"); if (mm) { $("#fModel").value = mm.dataset.model; showView("listings"); rerender(); }
  });
  $("#dlg").addEventListener("click", e => { if (e.target.id === "dlg" && lb.hidden) $("#dlg").close(); });

  load();
})();
