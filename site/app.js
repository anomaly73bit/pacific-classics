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
  let ALL = [], MODELS = [], MODEL_BY_ID = {}, REPORT = {}, META = {}, ADMIN = false;
  const keyOf = l => l.id || l.ref;
  // admin sees the purchase price; customers see the final price (car + Pacific Classics service)
  const priceOf = l => ADMIN ? l.price_eur
    : l.ref ? l.price                                                       // new public format: final price
    : l.price_eur ? Math.ceil(l.price_eur * 1.05 / 50) * 50 : null;          // older data file: compute it
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
    const [ls, models, checks] = await Promise.all([get("data/listings.json"), get("data/models.json"), get("data/checks.json")]);
    ALL = ls?.listings || []; META = ls?.meta || {}; MODELS = models || [];
    MODELS.forEach(m => { if (checks?.[m.id]?.length) m.it = { ...(m.it || {}), checks: checks[m.id] }; });
    const creds = (() => { try { return JSON.parse(sessionStorage.getItem("pc-admin") || "null"); } catch (e) { return null; } })();
    if (creds) {
      const bundle = await PCAdmin.open(creds.u, creds.p).catch(() => null);
      if (bundle) { ADMIN = true; ALL = bundle.listings; META = bundle.meta; REPORT = bundle.report || {}; }
      else { try { sessionStorage.removeItem("pc-admin"); } catch (e) {} }
    }
    document.body.classList.toggle("is-admin", ADMIN);
    document.body.classList.toggle("is-client", !ADMIN);
    $("#adminBar").hidden = !ADMIN;
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
      const pr = priceOf(l);
      if (pr != null && (pr < f.pmin || pr > f.pmax)) return false;
      if (pr == null && (f.pmin || f.pmax !== Infinity)) return false;
      if (l.year && (l.year < f.ymin || l.year > f.ymax)) return false;
      if (l.mileage_km && l.mileage_km > f.km) return false;
      if (f.hist === "fiva" && !l.historic?.fiva) return false;
      if (f.hist === "asi" && !l.historic?.asi) return false;
      if (f.seller && l.seller_type !== f.seller) return false;
      if (f.deals && !(has(l, "PRICE_DEAL") || has(l, "PRICE_DROP"))) return false;
      if (f.safe && l.alerts.some(a => RISKY.has(a.code))) return false;
      if (f.q) {
        const m = MODEL_BY_ID[l.model_id] || {};
        const hay = [l.ref, l.title, l.title_it, l.model_raw, l.city, l.region, COUNTRY[l.country], m.make, m.model, m.chassis].join(" ").toLowerCase();
        if (!f.q.split(/\s+/).every(w => hay.includes(w))) return false;
      }
      return true;
    });
    const by = {
      score: (a, b) => b.score - a.score,
      price_asc: (a, b) => (priceOf(a) ?? 9e9) - (priceOf(b) ?? 9e9),
      price_desc: (a, b) => (priceOf(b) ?? -1) - (priceOf(a) ?? -1),
      year: (a, b) => (a.year ?? 9999) - (b.year ?? 9999),
      km: (a, b) => (a.mileage_km ?? 9e9) - (b.mileage_km ?? 9e9),
      new: (a, b) => String(b.first_seen).localeCompare(String(a.first_seen)),
    }[f.sort];
    return out.sort(by);
  }

  // ---------- rendering
  function render() {
    const list = filtered();
    $("#count").textContent = T.results(list.filter(l => !l.sold).length) + (list.some(l => l.sold) ? " · " + T.soldCount(list.filter(l => l.sold).length) : "");
    const grid = $("#grid");
    grid.innerHTML = list.length ? list.slice(0, shown).map(card).join("") : `<div class="empty">${esc(T.noResults)}</div>`;
    $("#more").hidden = list.length <= shown;
    $("#more").textContent = `+ ${Math.min(PAGE, list.length - shown)}`;
    writeHash();
  }

  const tTitle = l => (lang === "it" && l.title_it) || l.title;
  const tDesc = l => (lang === "it" && l.description_it) || l.description;
  // the specific model of the ad inside its family ("Golf III" rather than "Passat B3/B4 / Golf III / Polo")
  const variantName = (l, m) => {
    const names = (mt(m, "model") || "").split(/\s+\/\s+/), chs = (m.chassis || "").split(/\s+\/\s+/);
    const i = Math.min(l.variant || 0, names.length - 1);
    return `${m.make} ${names[i]}${chs.length === names.length ? " (" + chs[i] + ")" : names.length === 1 ? " (" + m.chassis + ")" : ""}`;
  };
  const alertText = (a, m) => {
    const fn = T.alerts[a.code];
    const p = a.code === "ENGINE_BAD" && m ? { ...a.params, note: mt(m, "engine_bad_note") || "" } : (a.params || {});
    return fn ? fn(p) : a.code;
  };
  const sortAlerts = als => [...als].sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]);
  const mapUrl = l => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([l.zip, l.city, l.region, COUNTRY[l.country] || l.country].filter(Boolean).join(" "))}`;
  const priceHtml = l => priceOf(l) != null ? `€ ${fmt(priceOf(l))}` : "—";
  const histBadge = l => l.historic?.fiva ? `<span class="badge hist">FIVA ✓</span>` : l.historic?.asi ? `<span class="badge hist asi">ASI ✓</span>` : "";

  function card(l) {
    const m = MODEL_BY_ID[l.model_id] || {};
    const img = l.images?.[0];
    const keyAlerts = sortAlerts(l.alerts).filter(a => !["DEALER", "PRIVATE", "IMPORT_IT", "HIST_FIVA"].includes(a.code)).slice(0, 4);
    const specs = [l.year, l.mileage_km != null ? `${fmt(l.mileage_km)} km` : null, l.fuel, l.gearbox, l.power_kw ? `${l.power_kw} kW` : null].filter(Boolean);
    if (l.sold) return `<article class="card sold" aria-disabled="true" title="${esc(T.soldTitle)}">
      <div class="photo">${img ? `<img src="${esc(safeUrl(img))}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.src='img/placeholder.svg'">` : ""}
        <span class="sold-band">${esc(T.sold)}</span></div>
      <div class="body"><div class="top"><span class="price">${priceHtml(l)}</span></div>
        <h3 class="title">${esc(tTitle(l))}</h3>
        <div class="specs">${[l.year, l.mileage_km != null ? fmt(l.mileage_km) + " km" : null].filter(Boolean).map(x => `<span>${esc(x)}</span>`).join("")}</div>
        <div class="where">${flag(l.country)} <span>${esc(l.city || COUNTRY[l.country] || "")}</span></div>
      </div></article>`;
    const fr = l.price_rating?.frame;
    return `<article class="card${fr ? " frame-" + fr : ""}">
      <div class="photo" data-open="${esc(keyOf(l))}">
        ${img ? `<img src="${esc(safeUrl(img))}" alt="${esc(tTitle(l))}" loading="lazy" referrerpolicy="no-referrer" onerror="this.src='img/placeholder.svg'">` : `<img src="img/placeholder.svg" alt="">`}
        <span class="badge score ${l.score >= 75 ? "hi" : ""}" title="${esc(T.score)}">${l.score}</span>
        ${histBadge(l)}
        ${l.images?.length > 1 ? `<span class="badge nph">${esc(T.photos(l.images.length))}</span>` : ""}
      </div>
      <div class="body">
        <div class="top">
          <span class="price">${priceHtml(l)}</span>${ratingBadge(l)}
          ${ADMIN && l.currency && l.currency !== "EUR" && l.price ? `<span class="orig">${fmt(l.price)} ${esc(l.currency)}</span>` : ""}
        </div>
        <h3 class="title"${ADMIN ? ` title="${esc(l.title)}"` : ""}>${esc(tTitle(l))}</h3>
        <div class="specs">${specs.map(s => `<span>${esc(s)}</span>`).join("")}</div>
        <div class="where">${flag(l.country)} <span>${esc([l.zip, l.city].filter(Boolean).join(" ") || COUNTRY[l.country] || "")}</span>
          · <a href="${mapUrl(l)}" target="_blank" rel="noopener">${esc(T.map)}</a>
          · <span class="src">${ADMIN ? esc(SOURCE_NAMES[l.source] || l.source) + " · " : ""}${l.seller_type ? esc(T[l.seller_type]) : ""}</span></div>
        <div class="alerts">${keyAlerts.map(a => `<span class="al ${a.level}">${esc(alertText(a, m))}</span>`).join("")}</div>
        <div class="actions">${ADMIN ? `
          <button class="btn sec" data-open="${esc(keyOf(l))}">${esc(T.details)}</button>
          <a class="btn primary" href="${esc(safeUrl(l.url))}" target="_blank" rel="noopener nofollow">${esc(T.view(SOURCE_NAMES[l.source] || l.source))}</a>` : `
          <button class="btn primary" data-open="${esc(keyOf(l))}">${esc(T.openSheet)}</button>`}
        </div>
      </div>
    </article>`;
  }

  // indicative truck transport to northern/central Italy (midpoint of the ranges on the "Come funziona" page)
  const CONTACT_EMAIL = "info@pacificit.solutions", WHATSAPP = "420775368380";
  const TRANSPORT = { AT: 575, SI: 575, DE: 750, CZ: 800, SK: 800, FR: 800, BE: 950, NL: 950, LU: 950, ES: 1100, IT: 350, PL: 950, HU: 850 };
  const SOUTH_DE = /^(7|8|9)/;   // German postcodes 7xxxx-9xxxx: Baden-Württemberg / Bavaria
  const transportEstimate = l => l.country === "DE" && SOUTH_DE.test(l.zip || "") ? 625 : (TRANSPORT[l.country] ?? 900);
  const PAPERS = 350;
  function estimateHtml(l) {
    const pr = priceOf(l);
    if (!pr) return "";
    const commission = ADMIN && l.price_client ? l.price_client - pr : 0;      // admin: fee from the price ladder
    const tr = transportEstimate(l), tot = pr + commission + tr + PAPERS;
    return `<div class="panel est"><h3>${esc(T.estimate)}</h3>
      <table class="price-table">
        <tr><td>${esc(ADMIN ? T.estCarAdmin : T.estCar)}</td><td>€ ${fmt(pr)}</td></tr>
        ${ADMIN ? `<tr><td>${esc(T.estFee)}</td><td>€ ${fmt(commission)}</td></tr>` : ""}
        <tr><td>${esc(T.estTransport)}</td><td>≈ € ${fmt(tr)}</td></tr>
        <tr><td>${esc(T.estPapers)}</td><td>€ ${fmt(PAPERS)}</td></tr>
        <tr class="tot"><td>${esc(T.estTotal)}</td><td>≈ € ${fmt(Math.round(tot / 10) * 10)}</td></tr>
        <tr class="opt"><td>${esc(T.estInspection)}</td><td>${esc(T.onRequest)}</td></tr>
      </table>
      <p class="actions-row"><a class="btn wa" href="${quoteWa(l)}" target="_blank" rel="noopener">💬 WhatsApp</a>
      <a class="btn primary" href="${quoteMail(l)}">${esc(T.estQuote)}</a>
      <a class="btn sec" href="#" data-goto="service">${esc(T.estMore)}</a></p></div>`;
  }
  const carRef = l => !l ? "" : ADMIN ? l.url : `${l.ref} – ${tTitle(l)} (${location.origin}${location.pathname}#q=${l.ref})`;
  const quoteWa = l => `https://wa.me/${WHATSAPP}?text=${encodeURIComponent("Ciao Pacific Classics, vorrei un preventivo per questa auto: " + carRef(l))}`;
  const quoteMail = l => `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Preventivo Pacific Classics: " + (l?.title || ""))}&body=${encodeURIComponent((l ? "Auto: " + carRef(l) + "\n" : "Link o descrizione dell'auto: \n") + "Città di consegna: \nNome e telefono: \n")}`;

  // ---------- price verdict, documents
  const RATING = { great: "rGreat", good: "rGood", fair: "rFair", high: "rHigh", suspicious: "rSusp", unknown: "rUnknown" };
  function ratingBadge(l) {
    const r = l.price_rating; if (!r || !r.level || r.level === "unknown" || r.level === "fair") return "";
    return `<span class="rbadge ${r.frame || ""}">${esc(T[RATING[r.level]])}</span>`;
  }
  function verdictHtml(l) {
    const r = l.price_rating || {}, lvl = r.level || "unknown";
    const fair = r.fair ? (ADMIN ? r.fair : r.fair) : null;
    const danger = l.alerts.some(a => a.level === "danger");
    const cls = r.frame || "neutral";
    const body = lvl === "unknown" ? T.verdictUnknown
      : T.verdictText(lvl, Math.abs(r.pct), fmt(fair), r.peers);
    return `<div class="verdict ${cls}">
      <div class="v-title">${esc(T.verdictTitle)} · <b>${esc(T[RATING[lvl]])}</b></div>
      <p>${esc(body)}</p>
      ${danger ? `<p class="v-warn">${esc(T.verdictDanger)}</p>` : ""}
    </div>`;
  }
  function docsHtml(l) {
    const d = l.docs || {};
    const row = (k, label) => {
      const v = d[k], st = v === true ? "yes" : v === false ? "no" : "ask";
      const txt = v === true ? (k === "owners" && d.owners_n ? T.docOwners(d.owners_n) : T.docYes) : v === false ? T.docNo : T.docAsk;
      return `<li class="${st}"><span class="dot"></span><b>${esc(label)}</b><em>${esc(txt)}</em></li>`;
    };
    return `<div class="docs-box"><div class="v-title">${esc(T.docsTitle)}</div><ul>
      ${row("service_book", T.docService)}${row("invoices", T.docInvoices)}${row("inspections", T.docInspections)}${row("owners", T.docOwnersLabel)}
    </ul><p class="src">${esc(T.docsNote)}</p></div>`;
  }

  function openDetail(id) {
    const l = ALL.find(x => keyOf(x) === id); if (!l) return;
    const m = MODEL_BY_ID[l.model_id] || {};
    const h = l.historic || {}, ref = new Date().getFullYear();
    GALLERY = (l.images?.length ? l.images : ["img/placeholder.svg"]).map(safeUrl);
    const imgs = GALLERY.map((u, i) => `<img src="${esc(u)}" data-gi="${i}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.src='img/placeholder.svg'">`).join("");
    const rows = [
      [T.year, l.year], ["Km", l.mileage_km != null ? fmt(l.mileage_km) : null], [T.fuel, l.fuel], [T.gearbox, l.gearbox],
      [T.country, `${flag(l.country)} ${esc(COUNTRY[l.country] || l.country || "")}`],
      ["📍", `${esc([l.zip, l.city, l.region].filter(Boolean).join(" "))} · <a href="${mapUrl(l)}" target="_blank" rel="noopener">${esc(T.map)}</a>`],
      [T.ref, l.ref ? `<b>${esc(l.ref)}</b>` : null],
      [T.seller, `${esc(T[l.seller_type] || "–")}${ADMIN && l.seller_name ? " · " + esc(l.seller_name) : ""}`],
      ...(ADMIN ? [[T.median, REPORT.market?.[l.model_id] ? `€ ${fmt(REPORT.market[l.model_id].median_price)} (${REPORT.market[l.model_id].count})` : "–"],
                   ["Fonte", `${esc(SOURCE_NAMES[l.source] || l.source)}${l.currency !== "EUR" && l.price ? " · " + fmt(l.price) + " " + esc(l.currency) : ""}`]] : []),
    ].filter(r => r[1] != null && r[1] !== "");
    $("#dlgBody").innerHTML = `
      <div class="dlg-head"><h2>${priceHtml(l)} · ${esc(tTitle(l))}</h2><button class="x" aria-label="${esc(T.close)}" data-close>×</button></div>
      <div class="gallery">${imgs}</div>
      ${l.images?.length ? `<p class="hint">${esc(T.hoverHint)}</p>` : ""}
      <div class="verdict-row">${verdictHtml(l)}${docsHtml(l)}</div>
      <div class="dlg-grid">
        ${(m.it?.checks || []).length ? `<div class="panel checks">
          <h3>${esc(T.checksTitle(variantName(l, m)))}</h3>
          <ul class="chk">${m.it.checks.map(c => `<li>${esc(c)}</li>`).join("")}</ul>
          <p class="src">${esc(T.checksNote)}</p>
        </div>` : ""}
        <div class="panel">
          <h3>${esc(T.details)} · ${esc(T.score)} ${l.score}/100</h3>
          <div class="alerts col">${sortAlerts(l.alerts).map(a => `<span class="al ${a.level}">${esc(alertText(a, m))}</span>`).join("")}</div>
          ${l.highlights?.length ? `<h3 style="margin-top:16px">${esc(T.highlights)}</h3><ul class="hl">${l.highlights.map(h => `<li class="${h.startsWith("⚠") ? "warn" : ""}">${esc(h.replace(/^⚠\s*/, ""))}</li>`).join("")}</ul>` : ""}
        </div>
        ${estimateHtml(l)}
        <div class="panel">
          <dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${typeof v === "number" ? v : v}</dd>`).join("")}</dl>
        </div>
        <div class="panel">
          <h3>${esc(variantName(l, m))} <span class="stars">${"★".repeat(m.reliability || 0)}</span></h3>
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
          ${ADMIN && l.also_on?.length ? `<p>${esc(T.alsoOn)}: ${l.also_on.map(o => `<a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">${esc(SOURCE_NAMES[o.source] || o.source)}</a>`).join(", ")}</p>` : ""}
          ${ADMIN ? `<p style="margin-top:12px"><a class="btn primary" style="display:inline-block" href="${esc(safeUrl(l.url))}" target="_blank" rel="noopener nofollow">${esc(T.view(SOURCE_NAMES[l.source] || l.source))}</a></p>` : ""}
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

  function showView(v) {
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === v));
    document.querySelectorAll(".view").forEach(s => s.hidden = s.id !== "view-" + v);
    if (v === "models") renderModels();
    if (v === "service") scrollTo(0, 0);
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
    const g = e.target.closest("[data-goto]");
    if (g) { e.preventDefault(); if ($("#dlg").open) $("#dlg").close(); showView(g.dataset.goto); return; }
    const mm = e.target.closest("[data-model]"); if (mm) { $("#fModel").value = mm.dataset.model; showView("listings"); rerender(); }
  });
  $("#dlg").addEventListener("click", e => { if (e.target.id === "dlg" && lb.hidden) $("#dlg").close(); });

  $("#contactBtn").href = quoteMail(null);
  $("#logout").onclick = e => { e.preventDefault(); try { sessionStorage.removeItem("pc-admin"); } catch (x) {} location.reload(); };
  load();
})();
