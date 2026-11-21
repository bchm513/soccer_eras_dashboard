/* Eras of the Game — dashboard entry point.

   Every panel shares one monthly timeline. This file loads the data, builds the shared
   context (data, state, time helpers, actions), creates each panel, and runs the clock.

     time.js    frame <-> date <-> season
     map.js     countries, hubs, tournaments, moments
     peaks.js   career curves and era bands
     panel.js   the description of the current moment
     growth.js  growth-of-the-game sparklines
     table.js   era comparison table
     export.js  PNG and video export
*/
import { makeTime } from "./time.js";
import { createMap, VIEWS } from "./map.js";
import { createPeaks } from "./peaks.js";
import { createPanel } from "./panel.js";
import { createGrowth } from "./growth.js";
import { createTable } from "./table.js";
import { createExport } from "./export.js";

const REGION_LABELS = { world: "World", UEFA: "Europe", CONMEBOL: "S. America", CONCACAF: "N. America",
                        AFC: "Asia", CAF: "Africa", OFC: "Oceania" };

const [data, world] = await Promise.all([d3.json("data/eras.json"), d3.json("vendor/countries-110m.json")])
  .catch(() => {
    document.querySelector("main").innerHTML = `<section class="panel" style="padding:24px">
      <h2>No dashboard data yet</h2>
      <p>Run <code>python pipeline/build.py</code> in the project folder, then reload this page.</p></section>`;
    throw new Error("dashboard/data/eras.json not found");
  });
const M = data.meta;
const time = makeTime(M);
const N = time.N;
const regions = data.regions || {};
const state = { frame: 0, playing: false, metric: M.primaryMetric, selectedHub: null, hoverStar: null, region: "world" };

const ctx = {
  data, M, state, time,
  growth: data.growth || { series: [], countries: {}, leagueCoverage: {}, impact: {} },
  hubById: Object.fromEntries(data.hubs.map(h => [h.id, h])),
  // Which stars and eras the panels show: the world, or one confederation's own
  view() {
    const r = state.region !== "world" && regions[state.region];
    return r ? { stars: r.stars, eras: r.eras, series: r.series, regional: true, name: r.name }
             : { stars: data.stars, eras: data.eras[state.metric] || [], series: data.eraSeries[state.metric] || [],
                 regional: false, name: "World" };
  },
  setFrame, setPlaying, render,
};

if (M.sample) {
  const b = document.getElementById("sample-badge");
  b.hidden = false;
  b.title = M.note;
}

const map = createMap(ctx, world);
const peaks = createPeaks(ctx);
const panel = createPanel(ctx);
const growth = createGrowth(ctx);
const table = createTable(ctx);
const exporter = createExport(ctx);

// ---------- regions ----------
const regionBox = d3.select("#regions");
regionBox.selectAll("button").data(Object.keys(REGION_LABELS)).join("button")
  .attr("class", "chip").attr("data-region", d => d)
  .attr("title", d => d === "world" || regions[d] ? "" : "Zoom only: no regional star data yet")
  .text(d => REGION_LABELS[d])
  .on("click", (e, d) => setRegion(d));
function setRegion(name) {
  state.region = name;
  regionBox.selectAll("button").classed("on", d => d === name);
  map.zoomTo(name);
  peaks.bind();
  table.draw();
  render();
}

// ---------- clock ----------
const scrub = document.getElementById("scrub");
const clock = document.getElementById("clock");
const playBtn = document.getElementById("play");
scrub.max = N - 1;
scrub.addEventListener("input", () => { setPlaying(false); setFrame(+scrub.value); });
playBtn.addEventListener("click", () => setPlaying(!state.playing));
document.getElementById("metric").addEventListener("change", e => {
  state.metric = e.target.value;
  peaks.bind();
  table.draw();
  render();
});
document.addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
  if (e.code === "Space") { e.preventDefault(); setPlaying(!state.playing); }
  if (e.code === "ArrowRight") { setPlaying(false); setFrame(Math.min(N - 1, Math.floor(state.frame) + 1)); }
  if (e.code === "ArrowLeft") { setPlaying(false); setFrame(Math.max(0, Math.floor(state.frame) - 1)); }
});

let last = null, lastDesc = -1;
function setPlaying(p) {
  state.playing = p;
  playBtn.textContent = p ? "❚❚" : "▶";
  playBtn.setAttribute("aria-label", p ? "Pause" : "Play");
  if (p && state.frame >= N - 1) state.frame = 0;
  if (p) { last = null; requestAnimationFrame(tick); }
  else if (exporter.recording()) exporter.stop();
}
function setFrame(f) { state.frame = f; render(); }

function tick(ts) {
  if (!state.playing) return;
  if (last != null) {
    const speed = +document.getElementById("speed").value; // months per second
    state.frame = Math.min(N - 1, state.frame + ((ts - last) / 1000) * speed);
    if (state.frame >= N - 1) setPlaying(false);
  }
  last = ts;
  render(true);
  if (state.playing) requestAnimationFrame(tick);
}

function render(fromTick) {
  const f = state.frame;
  const m = map.draw(f);
  peaks.draw(f);
  growth.draw();
  clock.textContent = time.dateLabel(f);
  if (!fromTick || Math.floor(f) !== lastDesc) {     // the text panel only changes month to month
    panel.draw(m);
    table.mark(time.seasonOf(f));
    lastDesc = Math.floor(f);
  }
  scrub.value = Math.floor(f);
}

// Measures the data can't support (e.g. assists before 2012) are greyed out
document.querySelectorAll("#metric option").forEach(o => {
  const ok = (data.eras[o.value] || []).length > 0;
  o.disabled = !ok;
  if (!ok) o.textContent += " (no data yet)";
});

// ---------- deep links: ?t=2016-05&view=UEFA&metric=goals_raw&hub=hub7 ----------
const q = new URLSearchParams(location.search);
if (q.get("metric") && data.eras[q.get("metric")]) {
  state.metric = q.get("metric");
  document.getElementById("metric").value = state.metric;
}
if (q.get("hub") && ctx.hubById[q.get("hub")]) state.selectedHub = q.get("hub");
const t = /^(\d{4})-(\d{1,2})$/.exec(q.get("t") || "");
state.frame = t ? time.frameForMonth(+t[1], +t[2]) : time.frameForSeason(data.stars.length ? data.stars[0].peak : M.firstSeason);
regionBox.selectAll("button").classed("on", d => d === "world");
peaks.bind();
table.draw();
const startView = q.get("view");
if (startView && VIEWS[startView] && startView !== "world") setRegion(startView);
else render();
window.__eras = { state, setFrame, setPlaying, setRegion };   // handy for debugging
