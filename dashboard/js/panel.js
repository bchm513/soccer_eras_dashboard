// Description panel: what is happening at this moment — selected hub, champions, moments,
// tournaments, the era, the heart of the game, the stars near their peak.
import { MONTHS } from "./time.js";
import { inPeak } from "./peaks.js";

const METRIC_NAMES = { goals_adj: "goals, era-adjusted", goals_raw: "goals, raw", ga_adj: "goals + assists, era-adjusted" };
const pct = (w, total) => Math.round((100 * w) / total);

export function createPanel(ctx) {
  const { data, M, state, time, hubById } = ctx;
  const el = document.getElementById("desc");
  const cups = (M.competitions && M.competitions.cups) || {};
  const moments = data.moments || {};
  const clubAt = (s, season) => {
    const row = s.clubs.find(c => c[0] === season) || s.clubs.reduce((a, c) => (c[0] <= season ? c : a), s.clubs[0]);
    return row ? row[1] : null;
  };
  const block = (label, body, extra = "") => `<div class="d-block"${extra}>${label ? `<div class="d-label">${label}</div>` : ""}${body}</div>`;

  function selectedHub(map, season, total) {
    const h = hubById[state.selectedHub];
    const w = (map.hw.find(q => q.hub.id === h.id) || { w: 0 }).w;
    const listed = (data.hubPlayers && data.hubPlayers[h.id] && data.hubPlayers[h.id][String(season)]) ||
      data.stars.filter(s => s.clubs.some(c => c[0] === season && c[2] === h.id))
        .map(s => [s.name, clubAt(s, season) || "", null, null, true]);
    return `<div class="d-block"><button class="d-close" id="close-hub" aria-label="Close">×</button>
      <div class="d-label">Selected hub</div><div class="d-big">${h.name}</div>
      <div class="d-note">${h.cities.join(", ")}</div>
      <div class="d-note" style="margin-top:6px">${pct(w, total)}% of club weight this moment</div>
      <div class="bar"><i style="width:${(100 * w) / total}%"></i></div>
      ${listed.length ? `<div class="d-label" style="margin-top:10px">Top scorers here, ${time.seasonLabel(season)}</div>
        <ul class="d-list">${listed.map(p => `<li><span>${p[4] ? "★ " : ""}${p[0]}</span><span class="where">${p[2] != null ? p[2] + " goals · " : ""}${p[1] || ""}</span></li>`).join("")}</ul>`
        : `<div class="d-note" style="margin-top:6px">No standout scorers here this season.</div>`}</div>`;
  }

  function era(v, season, starById) {
    const e = v.eras.find(x => x.start <= season && season <= x.end);
    const label = `Era · ${v.regional ? v.name : METRIC_NAMES[state.metric]}`;
    if (e) {
      const hub = e.hub && hubById[e.hub] ? ` · heart: ${hubById[e.hub].name}` : "";
      return block(label, `<div class="d-big">Era ${v.eras.indexOf(e) + 1}: ${e.start}–${e.end}</div>
        <div class="d-note">${e.length} seasons · up to ${e.peakCount} stars peaking together (${e.peakYear})${hub}</div>
        <div class="d-note">Core: ${e.players.slice(0, 6).map(p => (starById[p] || {}).name || p).join(", ")}</div>`);
    }
    const next = v.eras.find(x => x.start > season), prev = [...v.eras].reverse().find(x => x.end < season);
    return block(label, `<div class="d-big">Between eras</div><div class="d-note">${prev ? `After ${prev.start}–${prev.end}` : "Before the first era"}${next ? ` · next begins ${next.start}` : ""}</div>`);
  }

  function draw(map) {
    const f = state.frame, d = time.dateOf(f), season = time.seasonOf(f), sp = time.seasonPos(f);
    const v = ctx.view();
    const starById = Object.fromEntries(v.stars.map(s => [s.id, s]));
    const total = map.hw.reduce((a, b) => a + b.w, 0) || 1;
    const topHubs = [...map.hw].sort((a, b) => b.w - a.w).filter(h => h.w > 0.05).slice(0, 4);
    const near = v.stars.filter(s => inPeak(s, sp)).sort((a, b) => b.height - a.height);
    const tours = map.tw.filter(t => f >= t.t.startFrame && f <= t.t.endFrame);

    let html = `<div class="d-date">${MONTHS[d.month - 1]} ${d.year}</div>
      <div class="d-season">Season ${time.seasonLabel(season)}${v.regional ? ` · ${v.name}` : ""}</div>`;
    if (state.selectedHub && hubById[state.selectedHub]) html += selectedHub(map, season, total);

    const champs = data.champions && data.champions[String(season)];
    if (champs) {
      html += block(`Continental champions ${time.seasonLabel(season)}`,
        Object.entries(champs).filter(([, c]) => c.winner).map(([comp, c]) =>
          `<div><b>🏆 ${c.winner[0]}</b> <span class="d-note">${cups[comp] || comp}${c.runner_up ? ` · beat ${c.runner_up[0]}` : ""}</span></div>`).join(""));
    }
    const mo = moments[String(season)] || [];
    if (mo.length) {
      html += block(`Moments of ${time.seasonLabel(season)}`,
        mo.slice(0, 6).map(m => `<div class="d-moment"><b>${m.title}</b><div class="d-note">${m.detail}</div></div>`).join("") +
        (mo.length > 6 ? `<div class="d-note">+ ${mo.length - 6} more</div>` : ""));
    }
    if (tours.length) {
      html += block("Tournament under way", tours.map(t => `<div class="d-tour">${t.t.type} ${t.t.year} · ${t.t.host}</div>`).join(""));
    }
    html += era(v, season, starById);
    html += block("Heart of the game", topHubs.length
      ? topHubs.map(h => `<div style="margin-bottom:5px"><div style="display:flex;justify-content:space-between"><span>${h.hub.name}</span><span class="where d-note">${pct(h.w, total)}%</span></div><div class="bar"><i style="width:${(100 * h.w) / total}%"></i></div></div>`).join("")
      : `<div class="d-note">No star hubs active.</div>`);
    html += block("Near their peak", near.length
      ? `<ul class="d-list">${near.map(s => `<li><span>${s.name}</span><span class="where">${clubAt(s, season) || ""}</span></li>`).join("")}</ul>`
      : `<div class="d-note">Nobody in a peak window right now.</div>`);
    if (!v.regional) {
      const agr = data.agreement.filter(a => a.a === state.metric || a.b === state.metric);
      html += block("Do the measures agree?", agr.map(a =>
        `<div class="d-note">${METRIC_NAMES[a.a === state.metric ? a.b : a.a]}: ${Math.round(a.jaccard * 100)}% overlap in era years (${a.from}–${a.to})</div>`).join(""));
    }
    if (M.sample) html += `<div class="d-block d-note">${M.note}</div>`;
    el.innerHTML = html;
    const c = document.getElementById("close-hub");
    if (c) c.onclick = () => { state.selectedHub = null; ctx.render(); };
  }

  return { draw };
}
