/* Eras of the Game — dashboard
   Three panels on one shared monthly timeline: map hubs, overlapping peaks, description. */
(async function () {
  const data = await d3.json("data/eras.json");
  const world = await d3.json("vendor/countries-110m.json");
  const M = data.meta;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [y0, m0] = M.start.split("-").map(Number);
  const N = M.frames;

  const state = { frame: 0, playing: false, metric: M.primaryMetric, selectedHub: null, hoverStar: null };
  const hubById = Object.fromEntries(data.hubs.map(h => [h.id, h]));
  const starById = Object.fromEntries(data.stars.map(s => [s.id, s]));

  if (M.sample) {
    const b = document.getElementById("sample-badge");
    b.hidden = false;
    b.title = M.note;
  }

  // ---------- time helpers ----------
  const dateOf = f => {
    const k = m0 - 1 + Math.floor(f);
    return { year: y0 + Math.floor(k / 12), month: (k % 12) + 1 };
  };
  // Club weights are anchored at December of each season's start year, so Dec Y => season Y.
  const seasonPos = f => { const d = dateOf(f); return d.year + (d.month - 12) / 12 + (f % 1) / 12; };
  const seasonOf = f => { const d = dateOf(f); return d.month >= 8 ? d.year : d.year - 1; };
  const frameForSeason = s => {
    const base = (Math.floor(s) - y0) * 12 + (12 - m0);
    return Math.max(0, Math.min(N - 1, Math.round(base + (s - Math.floor(s)) * 12)));
  };
  const lerp = (arr, f) => {
    const i = Math.floor(f), j = Math.min(i + 1, arr.length - 1), t = f - i;
    return arr[i] * (1 - t) + arr[j] * t;
  };

  // Tournament weights by frame
  const tourSeries = data.tournaments.map(t => {
    const arr = new Float32Array(N);
    t.weights.forEach(([f, w]) => { arr[f] = w; });
    return { ...t, arr };
  });

  const hubWeights = f => data.hubs.map(h => ({ hub: h, w: lerp(data.clubWeights[h.id], f) }));
  const tourWeights = f => tourSeries.map(t => ({ t, w: lerp(t.arr, f) })).filter(d => d.w > 0.01);

  const maxW = Math.max(
    ...Object.values(data.clubWeights).flat(),
    ...data.tournaments.flatMap(t => t.weights.map(w => w[1]))
  );

  // ---------- MAP ----------
  const MW = 960, MH = 520;
  const mapSvg = d3.select("#map").attr("viewBox", `0 0 ${MW} ${MH}`);
  const countries = topojson.feature(world, world.objects.countries);
  const projection = d3.geoNaturalEarth1();
  const view = {
    world: { type: "MultiPoint", coordinates: [[-125, -45], [60, 68], [140, 30]] },
    europe: { type: "MultiPoint", coordinates: [[-11, 36], [30, 60]] },
  };
  projection.fitExtent([[10, 10], [MW - 10, MH - 10]], view.world);
  const path = d3.geoPath(projection);
  const zoomLayer = mapSvg.append("g");
  zoomLayer.append("path").datum(d3.geoGraticule10()).attr("class", "graticule").attr("d", path);
  zoomLayer.append("g").selectAll("path").data(countries.features).join("path").attr("class", "country").attr("d", path);
  const r = d3.scaleSqrt().domain([0, maxW]).range([0, 46]);

  const hubG = zoomLayer.append("g");
  const tourG = zoomLayer.append("g");
  const leadRing = zoomLayer.append("circle").attr("class", "lead-ring").attr("r", 0);
  const labelG = zoomLayer.append("g");
  let k = 1;

  const zoom = d3.zoom().scaleExtent([1, 8]).on("zoom", e => {
    k = e.transform.k;
    zoomLayer.attr("transform", e.transform);
    drawMap(state.frame);
  });
  mapSvg.call(zoom);
  function zoomTo(name) {
    const b = path.bounds(view[name]);
    const s = Math.min(8, 0.92 / Math.max((b[1][0] - b[0][0]) / MW, (b[1][1] - b[0][1]) / MH));
    const tx = MW / 2 - s * (b[0][0] + b[1][0]) / 2, ty = MH / 2 - s * (b[0][1] + b[1][1]) / 2;
    mapSvg.transition().duration(700).call(zoom.transform, name === "world" ? d3.zoomIdentity : d3.zoomIdentity.translate(tx, ty).scale(s));
    document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === name));
  }
  document.querySelectorAll("[data-view]").forEach(b => b.addEventListener("click", () => zoomTo(b.dataset.view)));

  const tip = document.getElementById("tip");
  const showTip = (e, html) => { tip.innerHTML = html; tip.hidden = false; tip.style.left = e.clientX + 12 + "px"; tip.style.top = e.clientY + 12 + "px"; };
  const hideTip = () => { tip.hidden = true; };

  function drawMap(f) {
    const hw = hubWeights(f);
    const tw = tourWeights(f);
    const xy = d => projection([d.lon, d.lat]);
    // Circles keep their geographic size when zoomed but get a readable minimum
    const rad = w => Math.max(r(w), w > 0.05 ? 2 : 0) / Math.sqrt(k);

    hubG.selectAll("circle").data(hw, d => d.hub.id).join("circle")
      .attr("class", d => "hub" + (state.selectedHub === d.hub.id ? " selected" : ""))
      .attr("cx", d => xy(d.hub)[0]).attr("cy", d => xy(d.hub)[1])
      .attr("r", d => rad(d.w))
      .on("mousemove", (e, d) => showTip(e, `<b>${d.hub.name}</b><br>${d.hub.cities.join(", ")}`))
      .on("mouseleave", hideTip)
      .on("click", (e, d) => { setPlaying(false); state.selectedHub = d.hub.id; render(); });

    tourG.selectAll("circle").data(tw, d => d.t.id).join("circle")
      .attr("class", "tour")
      .attr("cx", d => xy(d.t)[0]).attr("cy", d => xy(d.t)[1])
      .attr("r", d => rad(d.w))
      .on("mousemove", (e, d) => showTip(e, `<b>${d.t.type} ${d.t.year}</b><br>${d.t.host}`))
      .on("mouseleave", hideTip)
      .on("click", () => setPlaying(false));

    const all = [...hw.map(d => ({ name: d.hub.name, lat: d.hub.lat, lon: d.hub.lon, w: d.w, tour: false })),
                 ...tw.map(d => ({ name: `${d.t.type} ${d.t.year}`, lat: d.t.lat, lon: d.t.lon, w: d.w, tour: true }))];
    const lead = all.reduce((a, b) => (b.w > a.w ? b : a), { w: 0 });
    if (lead.w > 0.05) {
      const [x, y] = xy(lead);
      leadRing.attr("cx", x).attr("cy", y).attr("r", rad(lead.w) + 5 / Math.sqrt(k)).attr("opacity", 1);
    } else leadRing.attr("opacity", 0);

    const shown = all.filter(d => rad(d.w) * k > 9 || d === lead).filter(d => d.w > 0.05);
    labelG.selectAll("text").data(shown, d => d.name).join("text")
      .attr("class", d => "hub-label" + (d.tour ? " tour-label" : ""))
      .attr("x", d => xy(d)[0]).attr("y", d => xy(d)[1] - rad(d.w) - 4 / k)
      .attr("text-anchor", "middle").style("font-size", `${11 / k}px`).style("stroke-width", `${3 / k}px`)
      .text(d => d.name);
    return { hw, tw, lead };
  }

  // ---------- PEAKS ----------
  const PW = 1200, PH = 330, pm = { t: 26, r: 18, b: 28, l: 40 };
  const peaksSvg = d3.select("#peaks").attr("viewBox", `0 0 ${PW} ${PH}`);
  const x = d3.scaleLinear().domain([M.firstSeason - 0.5, M.lastSeason + 1]).range([pm.l, PW - pm.r]);
  const yMax = d3.max(data.stars, s => d3.max(s.points, p => p[1]));
  const y = d3.scaleLinear().domain([-1.5, Math.ceil(yMax + 0.5)]).range([PH - pm.b, pm.t]);
  const bandG = peaksSvg.append("g");
  const strengthG = peaksSvg.append("path").attr("class", "strength");
  peaksSvg.append("g").attr("class", "axis").attr("transform", `translate(0,${PH - pm.b})`)
    .call(d3.axisBottom(x).ticks(16).tickFormat(d3.format("d")));
  peaksSvg.append("g").attr("class", "axis").attr("transform", `translate(${pm.l},0)`).call(d3.axisLeft(y).ticks(6));
  peaksSvg.append("text").attr("x", pm.l + 4).attr("y", pm.t - 10).attr("class", "peak-label")
    .text("Output vs league average (z)");
  peaksSvg.append("line").attr("class", "flag-line").attr("x1", pm.l).attr("x2", PW - pm.r)
    .attr("y1", y(M.flagZ)).attr("y2", y(M.flagZ));
  peaksSvg.append("text").attr("class", "peak-label").attr("x", PW - pm.r - 4).attr("y", y(M.flagZ) - 4)
    .attr("text-anchor", "end").text(`star threshold z = ${M.flagZ}`);

  const line = d3.line().x(d => x(d[0])).y(d => y(d[1])).curve(d3.curveMonotoneX);
  const starG = peaksSvg.append("g").selectAll("g").data(data.stars).join("g");
  starG.selectAll(".pt").data(s => s.points).join("circle").attr("class", "pt")
    .attr("cx", d => x(d[0])).attr("cy", d => y(d[1])).attr("r", 2);
  starG.append("path").attr("class", "curve").attr("d", s => line(s.curve));
  starG.append("text").attr("class", "peak-label")
    .attr("x", s => x(s.peak)).attr("y", s => y(s.height) - 6).attr("text-anchor", "middle")
    .text(s => s.name.replace("Player ", ""));
  starG.append("path").attr("class", "curve-hit").attr("d", s => line(s.curve))
    .on("mousemove", (e, s) => { state.hoverStar = s.id; drawPeaksHighlight(); showTip(e, `<b>${s.name}</b><br>Peak ${s.peak.toFixed(1)} · window ${Math.round(s.window[0])}–${Math.round(s.window[1])}`); })
    .on("mouseleave", () => { state.hoverStar = null; drawPeaksHighlight(); hideTip(); })
    .on("click", (e, s) => { setPlaying(false); setFrame(frameForSeason(s.peak)); });
  const playhead = peaksSvg.append("line").attr("class", "playhead").attr("y1", pm.t).attr("y2", PH - pm.b);

  function drawEras() {
    const eras = data.eras[state.metric] || [];
    const g = bandG.selectAll("g").data(eras, d => state.metric + d.id).join(enter => {
      const gg = enter.append("g");
      gg.append("rect").attr("class", "era-band");
      gg.append("text").attr("class", "era-label");
      return gg;
    });
    g.select("rect").attr("x", d => x(d.start - 0.5)).attr("width", d => x(d.end + 0.5) - x(d.start - 0.5))
      .attr("y", pm.t).attr("height", PH - pm.t - pm.b).attr("rx", 3);
    g.select("text").attr("x", d => x(d.start - 0.5) + 4).attr("y", PH - pm.b - 6)
      .text(d => `${d.start}–${d.end}`);
    const series = data.eraSeries[state.metric] || [];
    const sy = d3.scaleLinear().domain([0, d3.max(series, d => d.strength) || 1]).range([PH - pm.b, PH - pm.b - 46]);
    strengthG.attr("d", d3.area().x(d => x(d.year)).y0(PH - pm.b).y1(d => sy(d.strength)).curve(d3.curveMonotoneX)(series));
  }

  function inPeak(s, sp) { return s.window[0] - 0.5 <= sp && sp <= s.window[1] + 0.5; }
  function drawPeaksHighlight() {
    const sp = seasonPos(state.frame);
    starG.each(function (s) {
      const on = inPeak(s, sp);
      const g = d3.select(this);
      g.select(".curve").classed("on", on).classed("hover", state.hoverStar === s.id);
      g.selectAll(".pt").classed("on", on);
      g.select(".peak-label").classed("on", on);
    });
  }

  // ---------- DESCRIPTION ----------
  const desc = document.getElementById("desc");
  const metricName = { goals_adj: "goals, era-adjusted", goals_raw: "goals, raw", ga_adj: "goals + assists, era-adjusted" };
  const clubAt = (s, season) => {
    const row = s.clubs.find(c => c[0] === season) || s.clubs.reduce((a, c) => (c[0] <= season ? c : a), s.clubs[0]);
    return row ? row[1] : null;
  };
  const hubShort = id => (hubById[id] ? hubById[id].name : "—");

  function drawDesc(map) {
    const f = state.frame, d = dateOf(f), season = seasonOf(f), sp = seasonPos(f);
    const eras = data.eras[state.metric] || [];
    const era = eras.find(e => e.start <= season && season <= e.end);
    const idx = era ? eras.indexOf(era) + 1 : 0;
    const total = map.hw.reduce((a, b) => a + b.w, 0) || 1;
    const topHubs = [...map.hw].sort((a, b) => b.w - a.w).filter(h => h.w > 0.05).slice(0, 4);
    const near = data.stars.filter(s => inPeak(s, sp)).sort((a, b) => b.height - a.height);
    const tours = map.tw.filter(t => f >= t.t.startFrame && f <= t.t.endFrame);

    let html = `<div class="d-date">${MONTHS[d.month - 1]} ${d.year}</div>
      <div class="d-season">Season ${season}–${String((season + 1) % 100).padStart(2, "0")}</div>`;

    if (state.selectedHub) {
      const h = hubById[state.selectedHub];
      const w = (map.hw.find(x => x.hub.id === h.id) || { w: 0 }).w;
      const players = data.stars.filter(s => s.clubs.some(c => c[0] === season && c[2] === h.id));
      html += `<div class="d-block"><button class="d-close" id="close-hub" aria-label="Close">×</button>
        <div class="d-label">Selected hub</div><div class="d-big">${h.name}</div>
        <div class="d-note">${h.cities.join(", ")}</div>
        <div class="d-note" style="margin-top:6px">${Math.round((100 * w) / total)}% of club weight this moment</div>
        <div class="bar"><i style="width:${(100 * w) / total}%"></i></div>
        ${players.length ? `<ul class="d-list">${players.map(s => `<li><span>${s.name}</span><span class="where">${clubAt(s, season) || ""}</span></li>`).join("")}</ul>`
          : `<div class="d-note" style="margin-top:6px">No star players here this season.</div>`}</div>`;
    }

    if (tours.length) {
      html += `<div class="d-block"><div class="d-label">Tournament under way</div>
        ${tours.map(t => `<div class="d-tour">${t.t.type} ${t.t.year} · ${t.t.host}</div>`).join("")}</div>`;
    }

    html += `<div class="d-block"><div class="d-label">Era · ${metricName[state.metric]}</div>`;
    if (era) {
      html += `<div class="d-big">Era ${idx}: ${era.start}–${era.end}</div>
        <div class="d-note">${era.length} seasons · up to ${era.peakCount} stars peaking together (${era.peakYear})${era.hub ? ` · heart: ${hubShort(era.hub)}` : ""}</div>
        <div class="d-note">Core: ${era.players.slice(0, 6).map(p => (starById[p] || {}).name || p).join(", ")}</div>`;
    } else {
      const next = eras.find(e => e.start > season), prev = [...eras].reverse().find(e => e.end < season);
      html += `<div class="d-big">Between eras</div><div class="d-note">${prev ? `After ${prev.start}–${prev.end}` : "Before the first era"}${next ? ` · next begins ${next.start}` : ""}</div>`;
    }
    html += `</div>`;

    html += `<div class="d-block"><div class="d-label">Heart of the game</div>
      ${topHubs.length ? topHubs.map(h => `<div style="margin-bottom:5px"><div style="display:flex;justify-content:space-between"><span>${h.hub.name}</span><span class="where d-note">${Math.round((100 * h.w) / total)}%</span></div><div class="bar"><i style="width:${(100 * h.w) / total}%"></i></div></div>`).join("") : `<div class="d-note">No star hubs active.</div>`}</div>`;

    html += `<div class="d-block"><div class="d-label">Near their peak</div>
      ${near.length ? `<ul class="d-list">${near.map(s => `<li><span>${s.name}</span><span class="where">${clubAt(s, season) || ""}</span></li>`).join("")}</ul>` : `<div class="d-note">Nobody in a peak window right now.</div>`}</div>`;

    const agr = data.agreement.filter(a => a.a === state.metric || a.b === state.metric);
    html += `<div class="d-block"><div class="d-label">Do the measures agree?</div>
      ${agr.map(a => `<div class="d-note">${metricName[a.a === state.metric ? a.b : a.a]}: ${Math.round(a.jaccard * 100)}% overlap in era years (${a.from}–${a.to})</div>`).join("")}</div>`;

    if (M.sample) html += `<div class="d-block d-note">${M.note}</div>`;
    desc.innerHTML = html;
    const c = document.getElementById("close-hub");
    if (c) c.onclick = () => { state.selectedHub = null; render(); };
  }

  // ---------- CONTROLS ----------
  const scrub = document.getElementById("scrub");
  const clock = document.getElementById("clock");
  const playBtn = document.getElementById("play");
  scrub.max = N - 1;
  scrub.addEventListener("input", () => { setPlaying(false); setFrame(+scrub.value); });
  playBtn.addEventListener("click", () => setPlaying(!state.playing));
  document.getElementById("metric").addEventListener("change", e => { state.metric = e.target.value; drawEras(); render(); });
  document.addEventListener("keydown", e => {
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
    if (e.code === "Space") { e.preventDefault(); setPlaying(!state.playing); }
    if (e.code === "ArrowRight") { setPlaying(false); setFrame(Math.min(N - 1, Math.floor(state.frame) + 1)); }
    if (e.code === "ArrowLeft") { setPlaying(false); setFrame(Math.max(0, Math.floor(state.frame) - 1)); }
  });

  function setPlaying(p) {
    state.playing = p;
    playBtn.textContent = p ? "❚❚" : "▶";
    playBtn.setAttribute("aria-label", p ? "Pause" : "Play");
    if (p && state.frame >= N - 1) state.frame = 0;
    if (p) { last = null; requestAnimationFrame(tick); }
  }
  function setFrame(f) { state.frame = f; render(); }

  let last = null, lastDesc = -1;
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
    const map = drawMap(f);
    drawPeaksHighlight();
    playhead.attr("x1", x(seasonPos(f))).attr("x2", x(seasonPos(f)));
    const d = dateOf(f);
    clock.textContent = `${MONTHS[d.month - 1]} ${d.year}`;
    if (!fromTick || Math.floor(f) !== lastDesc) { drawDesc(map); lastDesc = Math.floor(f); }
    scrub.value = Math.floor(f);
  }

  // Measures the data can't support (e.g. assists in real data) are greyed out
  document.querySelectorAll("#metric option").forEach(o => {
    const ok = (data.eras[o.value] || []).length > 0;
    o.disabled = !ok;
    if (!ok) o.textContent += " (no data yet)";
  });

  // Deep links: ?t=2026-07&view=europe&metric=goals_raw&hub=hub7
  const q = new URLSearchParams(location.search);
  if (q.get("metric") && data.eras[q.get("metric")]) {
    state.metric = q.get("metric");
    document.getElementById("metric").value = state.metric;
  }
  if (q.get("hub") && hubById[q.get("hub")]) state.selectedHub = q.get("hub");
  drawEras();
  const t = /^(\d{4})-(\d{1,2})$/.exec(q.get("t") || "");
  setFrame(t ? Math.max(0, Math.min(N - 1, (+t[1] - y0) * 12 + (+t[2] - m0)))
             : frameForSeason(data.stars.length ? data.stars[0].peak : M.firstSeason));
  if (q.get("view") === "europe") zoomTo("europe");
  window.__eras = { state, setFrame, setPlaying }; // handy for debugging
})();
