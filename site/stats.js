// Pacific Classics — visit tracking (public) and statistics page (admin only)
window.PCStats = (() => {
  const URL_ = window.PC_STATS_URL || "https://stats.pacificit.solutions";
  let sentPage = false;

  // ---- tracking: anonymous, no cookies; never called for the administrator
  function track(kind, data) {
    try {
      const body = JSON.stringify({ kind, ...data });
      if (navigator.sendBeacon) navigator.sendBeacon(URL_ + "/hit", body);
      else fetch(URL_ + "/hit", { method: "POST", body, keepalive: true, mode: "no-cors" });
    } catch (e) { /* statistics must never break the site */ }
  }
  function page(view) {
    if (sentPage) return; sentPage = true;
    track("page", { view, referrer: document.referrer || "" });
  }

  // ---- admin page
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = n => n == null ? "–" : Number(n).toLocaleString("it-IT");
  const flag = cc => cc && cc.length === 2 ? String.fromCodePoint(...[...cc.toUpperCase()].map(c => 127397 + c.charCodeAt(0))) : "";
  const countryName = cc => { try { return new Intl.DisplayNames(["it"], { type: "region" }).of(cc); } catch (e) { return cc; } };
  let map, layer;

  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    return new Promise((ok, ko) => {
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css";
      document.head.appendChild(css);
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js";
      s.onload = ok; s.onerror = ko; document.head.appendChild(s);
    });
  }

  function bars(rows) {
    if (!rows.length) return `<p class="src">Nessuna visita nel periodo.</p>`;
    const max = Math.max(1, ...rows.map(r => r.visitors || 0));
    return `<div class="bars">${rows.map(r => {
      const h = Math.round((r.visitors || 0) / max * 100);
      const d = new Date(r.day + "T00:00:00");
      return `<div class="bar" title="${esc(d.toLocaleDateString("it-IT"))}: ${r.visitors} visitatori, ${r.views} pagine, ${r.car_views} schede auto">
        <span style="height:${h}%"></span><em>${d.getDate()}</em></div>`;
    }).join("")}</div>`;
  }

  async function render(box, creds, listings, openCar) {
    const days = +(box.querySelector("#stDays")?.value || 30);
    box.querySelector("#stBody").innerHTML = `<p class="src">Caricamento…</p>`;
    let s;
    try {
      const r = await fetch(`${URL_}/stats?days=${days}`, { headers: { Authorization: "Basic " + btoa(`${creds.u}:${creds.p}`) }, cache: "no-store" });
      if (!r.ok) throw new Error(r.status === 401 ? "Credenziali non accettate dal contatore" : "HTTP " + r.status);
      s = await r.json();
    } catch (e) {
      box.querySelector("#stBody").innerHTML = `<div class="panel"><b>Statistiche non disponibili.</b><p class="src">${esc(e.message)}. Il contatore visite non è ancora attivo oppure non raggiungibile.</p></div>`;
      return;
    }
    const byRef = Object.fromEntries((listings || []).map(l => [l.ref, l]));
    const t = s.totals || {};
    box.querySelector("#stBody").innerHTML = `
      <div class="tiles">
        <div><b>${fmt(t.visitors)}</b><span>visitatori</span></div>
        <div><b>${fmt(t.views)}</b><span>pagine viste</span></div>
        <div><b>${fmt(t.car_views)}</b><span>schede auto aperte</span></div>
        <div><b>${fmt(t.quotes)}</b><span>richieste di preventivo</span></div>
      </div>
      <div class="panel"><h3>Visitatori al giorno</h3>${bars(s.daily || [])}</div>
      <div class="cols">
        <div class="panel"><h3>Da dove arrivano</h3><div id="stMap" class="st-map"></div></div>
        <div class="panel"><h3>Paesi</h3><table class="price-table">
          <tr><th>Paese</th><th>Visitatori</th></tr>
          ${(s.countries || []).slice(0, 25).map(c => `<tr><td>${flag(c.country)} ${esc(countryName(c.country))}</td><td>${fmt(c.visitors)}</td></tr>`).join("") || `<tr><td colspan="2">–</td></tr>`}
        </table></div>
      </div>
      <div class="panel"><h3>Auto più viste</h3><table class="price-table st-cars">
        <tr><th>Auto</th><th>Aperture</th><th>Visitatori</th><th>Preventivi</th></tr>
        ${(s.cars || []).map(c => { const l = byRef[c.ref];
          return `<tr><td><a href="#" data-stcar="${esc(c.ref)}">${l?.images?.[0] ? `<img src="${esc(l.images[0])}" alt="" referrerpolicy="no-referrer">` : ""}
            <span><b>${esc(c.ref)}</b> ${esc(c.title || l?.title || "")}${l ? "" : " <em>(non più online)</em>"}</span></a></td>
            <td>${fmt(c.views)}</td><td>${fmt(c.visitors)}</td><td>${fmt(c.quotes)}</td></tr>`; }).join("") || `<tr><td colspan="4">–</td></tr>`}
      </table></div>
      <div class="cols">
        <div class="panel"><h3>Mese per mese</h3><table class="price-table"><tr><th>Mese</th><th>Visitatori</th><th>Pagine</th></tr>
          ${(s.monthly || []).map(m => `<tr><td>${esc(m.month)}</td><td>${fmt(m.visitors)}</td><td>${fmt(m.views)}</td></tr>`).join("") || `<tr><td colspan="3">–</td></tr>`}</table></div>
        <div class="panel"><h3>Provenienza e dispositivi</h3><table class="price-table"><tr><th>Arrivati da</th><th>Visitatori</th></tr>
          ${(s.referrers || []).map(r => `<tr><td>${esc(r.referrer)}</td><td>${fmt(r.visitors)}</td></tr>`).join("") || `<tr><td colspan="2">–</td></tr>`}</table>
          <p class="src">${(s.devices || []).map(d => `${d.device === "mobile" ? "📱 Telefono" : "💻 Computer"}: ${fmt(d.visitors)}`).join(" · ")}</p></div>
      </div>
      <p class="src">Dati anonimi: nessun cookie e nessun indirizzo IP salvato. Le tue visite da amministratore non vengono contate.</p>`;
    box.querySelectorAll("[data-stcar]").forEach(a => a.onclick = e => { e.preventDefault(); openCar(a.dataset.stcar); });
    try {
      await loadLeaflet();
      if (map) { map.remove(); map = null; }
      map = L.map("stMap", { worldCopyJump: true }).setView([46, 10], 3);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 10, attribution: "© OpenStreetMap" }).addTo(map);
      const max = Math.max(1, ...(s.places || []).map(p => p.visitors));
      layer = L.layerGroup((s.places || []).map(p => L.circleMarker([p.lat, p.lon], {
        radius: 5 + 18 * Math.sqrt(p.visitors / max), color: "#14213d", weight: 1, fillColor: "#c9a227", fillOpacity: .75,
      }).bindTooltip(`${esc(p.city || "")} ${flag(p.country)} · ${p.visitors} visitatori`))).addTo(map);
    } catch (e) {
      box.querySelector("#stMap").innerHTML = `<p class="src">Mappa non disponibile.</p>`;
    }
  }

  function mount(box, creds, listings, openCar) {
    if (!box.dataset.ready) {
      box.innerHTML = `<div class="st-head"><h1>Statistiche visite</h1>
        <label>Periodo <select id="stDays"><option value="7">7 giorni</option><option value="30" selected>30 giorni</option>
        <option value="90">90 giorni</option><option value="365">12 mesi</option></select></label></div><div id="stBody"></div>`;
      box.querySelector("#stDays").onchange = () => render(box, creds, listings, openCar);
      box.dataset.ready = "1";
    }
    render(box, creds, listings, openCar);
  }

  return { track, page, mount };
})();
