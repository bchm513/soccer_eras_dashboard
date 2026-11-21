/* Eras of the Game — dashboard
   Panels on one shared monthly timeline: map hubs, overlapping peaks, description,
   growth of the game, and an era comparison table. Regions switch the peaks and eras to
   that confederation's own stars; the map can be exported as an image or a video clip. */
(async function () {
  const data = await d3.json("data/eras.json");
  const world = await d3.json("vendor/countries-110m.json");
  const M = data.meta;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [y0, m0] = M.start.split("-").map(Number);
  const N = M.frames;
  const REGIONS = data.regions || {};
  const GROWTH = data.growth || { series: [], countries: {}, leagueCoverage: {}, impact: {} };
  const CUPS = { UCL: "Champions League", LIB: "Copa Libertadores", ACL: "AFC Champions League",
                 CAF: "CAF Champions League", CCL: "CONCACAF Champions Cup" };
  const VIEWS = {
    world: [[-125, -45], [60, 68], [140, 30]],
    UEFA: [[-11, 35], [45, 62]], CONMEBOL: [[-82, -56], [-34, 12]], CONCACAF: [[-125, 7], [-60, 50]],
    AFC: [[45, -10], [150, 55]], CAF: [[-18, -35], [52, 37]], OFC: [[110, -48], [180, 0]],
  };
  const VIEW_NAMES = Object.assign({ world: "World" }, M.confedNames || {});

  const state = { frame: 0, playing: false, metric: M.primaryMetric, selectedHub: null, hoverStar: null, region: "world" };
  const hubById = Object.fromEntries(data.hubs.map(h => [h.id, h]));

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
  const seasonLabel = s => `${s}–${String((s + 1) % 100).padStart(2, "0")}`;
  const frameForSeason = s => {
    const base = (Math.floor(s) - y0) * 12 + (12 - m0);
    return Math.max(0, Math.min(N - 1, Math.round(base + (s - Math.floor(s)) * 12)));
  };
  const lerp = (arr, f) => {
    const i = Math.floor(f), j = Math.min(i + 1, arr.length - 1), t = f - i;
    return arr[i] * (1 - t) + arr[j] * t;
  };

  const tourSeries = data.tournaments.map(t => {
    const arr = new Float32Array(N);
    t.weights.forEach(([f, w]) => { arr[f] = w; });
    return { ...t, arr };
  });
  const hubWeights = f => data.hubs.map(h => ({ hub: h, w: lerp(data.clubWeights[h.id], f) }));
  const tourWeights = f => tourSeries.map(t => ({ t, w: lerp(t.arr, f) })).filter(d => d.w > 0.01);
  const maxW = Math.max(1e-6, ...Object.values(data.clubWeights).flat(),
                        ...data.tournaments.flatMap(t => t.weights.map(w => w[1])));

  // Which stars / eras the peaks panel and table show: the world, or one confederation
  const view = () => {
    const r = state.region !== "world" && REGIONS[state.region];
    return r ? { stars: r.stars, eras: r.eras, series: r.series, regional: true, name: r.name }
             : { stars: data.stars, eras: data.eras[state.metric] || [], series: data.eraSeries[state.metric] || [],
                 regional: false, name: "World" };
  };

  // ---------- MAP ----------
  const MW = 960, MH = 520;
  const mapSvg = d3.select("#map").attr("viewBox", `0 0 ${MW} ${MH}`);
  const defs = mapSvg.append("defs");
  const hatch = defs.append("pattern").attr("id", "hatch").attr("patternUnits", "userSpaceOnUse")
    .attr("width", 5).attr("height", 5).attr("patternTransform", "rotate(45)");
  hatch.append("rect").attr("class", "hatch-bg").attr("width", 5).attr("height", 5);
  hatch.append("line").attr("class", "hatch-line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 5);
  mapSvg.append("rect").attr("class", "sea").attr("width", MW).attr("height", MH);
  const countries = topojson.feature(world, world.objects.countries);
  const projection = d3.geoNaturalEarth1();
  projection.fitExtent([[10, 10], [MW - 10, MH - 10]], { type: "MultiPoint", coordinates: VIEWS.world });
  const path = d3.geoPath(projection);
  const zoomLayer = mapSvg.append("g");
  zoomLayer.append("path").datum(d3.geoGraticule10()).attr("class", "graticule").attr("d", path);
  const countryPaths = zoomLayer.append("g").selectAll("path").data(countries.features).join("path")
    .attr("class", "country").attr("d", path);
  const r = d3.scaleSqrt().domain([0, maxW]).range([0, 46]);
  const hubG = zoomLayer.append("g");
  const tourG = zoomLayer.append("g");
  const leadRing = zoomLayer.append("circle").attr("class", "lead-ring").attr("r", 0);
  const momentG = zoomLayer.append("g");
  const MOMENTS = data.moments || {};
  const labelG = zoomLayer.append("g");
  const mapDate = mapSvg.append("text").attr("class", "map-date").attr("x", 18).attr("y", 46);
  const mapSub = mapSvg.append("text").attr("class", "map-sub").attr("x", 20).attr("y", 66);
  let k = 1;

  const zoom = d3.zoom().scaleExtent([1, 8]).on("zoom", e => {
    k = e.transform.k;
    zoomLayer.attr("transform", e.transform);
    drawMap(state.frame);
  });
  mapSvg.call(zoom);
  function zoomTo(name) {
    const b = path.bounds({ type: "MultiPoint", coordinates: VIEWS[name] || VIEWS.world });
    const s = Math.min(8, 0.92 / Math.max((b[1][0] - b[0][0]) / MW, (b[1][1] - b[0][1]) / MH));
    const tx = MW / 2 - s * (b[0][0] + b[1][0]) / 2, ty = MH / 2 - s * (b[0][1] + b[1][1]) / 2;
    mapSvg.transition().duration(700).call(zoom.transform,
      name === "world" ? d3.zoomIdentity : d3.zoomIdentity.translate(tx, ty).scale(s));
  }

  // Region buttons: always the zoom presets; regions with their own stars switch the panels too
  const regionBox = d3.select("#regions");
  const regionKeys = ["world", "UEFA", "CONMEBOL", "CONCACAF", "AFC", "CAF", "OFC"];
  regionBox.selectAll("button").data(regionKeys).join("button")
    .attr("class", "chip").attr("data-region", d => d)
    .attr("title", d => d === "world" || REGIONS[d] ? "" : "Zoom only: no regional star data yet")
    .text(d => ({ world: "World", UEFA: "Europe", CONMEBOL: "S. America", CONCACAF: "N. America",
                  AFC: "Asia", CAF: "Africa", OFC: "Oceania" })[d])
    .on("click", (e, d) => setRegion(d));
  function setRegion(name) {
    state.region = name;
    regionBox.selectAll("button").classed("on", d => d === name);
    zoomTo(name);
    bindPeaks();
    drawTable();
    render();
  }

  // Countries: not yet playing internationals / playing without league data / league data
  let lastCountrySeason = null;
  function drawCountries(season) {
    if (season === lastCountrySeason || !Object.keys(GROWTH.countries).length) return;
    lastCountrySeason = season;
    countryPaths.attr("class", f => {
      const name = f.properties.name, first = GROWTH.countries[name], cov = GROWTH.leagueCoverage[name];
      if (first == null || season < first) return "country c-none";
      if (cov && cov[0] <= season && season <= cov[1]) return "country c-league";
      return "country c-play";
    });
  }

  const tip = document.getElementById("tip");
  const showTip = (e, html) => { tip.innerHTML = html; tip.hidden = false; tip.style.left = e.clientX + 12 + "px"; tip.style.top = e.clientY + 12 + "px"; };
  const hideTip = () => { tip.hidden = true; };
  countryPaths.on("mousemove", (e, f) => {
    const name = f.properties.name, first = GROWTH.countries[name], cov = GROWTH.leagueCoverage[name];
    if (first == null && !cov) return hideTip();
    showTip(e, `<b>${name}</b>${first != null ? `<br>First international: ${first}` : ""}` +
               (cov ? `<br>League data: ${cov[0]}–${cov[1]}` : "<br>No league data yet"));
  }).on("mouseleave", hideTip);

  function drawMap(f) {
    const hw = hubWeights(f);
    const tw = tourWeights(f);
    const xy = d => projection([d.lon, d.lat]);
    const rad = w => Math.max(r(w), w > 0.05 ? 2 : 0) / Math.sqrt(k);   // readable minimum when zoomed
    drawCountries(seasonOf(f));

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

    // This season's big moments, as small diamonds (hover for the story)
    const mo = (MOMENTS[String(seasonOf(f))] || []).filter(m => m.lat != null && m.lon != null);
    momentG.selectAll("path").data(mo, m => m.title).join("path")
      .attr("class", m => "moment " + m.kind)
      .attr("transform", m => { const [px, py] = xy(m); return `translate(${px},${py}) scale(${1 / Math.sqrt(k)})`; })
      .attr("d", d3.symbol(d3.symbolDiamond, 60)())
      .on("mousemove", (e, m) => showTip(e, `<b>${m.title}</b><br>${m.detail}`))
      .on("mouseleave", hideTip)
      .on("click", () => setPlaying(false));

    const dt = dateOf(f);
    mapDate.text(`${MONTHS[dt.month - 1]} ${dt.year}`);
    mapSub.text(lead.w > 0.05 ? `Heart of the game: ${lead.name}` : "");
    return { hw, tw, lead };
  }

  // ---------- PEAKS ----------
  const PW = 1200, PH = 330, pm = { t: 26, r: 18, b: 28, l: 40 };
  const peaksSvg = d3.select("#peaks").attr("viewBox", `0 0 ${PW} ${PH}`);
  const x = d3.scaleLinear().domain([M.firstSeason - 0.5, M.lastSeason + 1]).range([pm.l, PW - pm.r]);
  const y = d3.scaleLinear().range([PH - pm.b, pm.t]).clamp(true);
  const bandG = peaksSvg.append("g");
  const strengthG = peaksSvg.append("path").attr("class", "strength");
  peaksSvg.append("g").attr("class", "axis").attr("transform", `translate(0,${PH - pm.b})`)
    .call(d3.axisBottom(x).ticks(16).tickFormat(d3.format("d")));
  const yAxis = peaksSvg.append("g").attr("class", "axis").attr("transform", `translate(${pm.l},0)`);
  peaksSvg.append("text").attr("x", pm.l + 4).attr("y", pm.t - 10).attr("class", "peak-label")
    .text("Output vs league average (z)");
  const flagLine = peaksSvg.append("line").attr("class", "flag-line").attr("x1", pm.l).attr("x2", PW - pm.r);
  const flagText = peaksSvg.append("text").attr("class", "peak-label").attr("x", PW - pm.r - 4).attr("text-anchor", "end")
    .text(`star threshold z = ${M.flagZ}`);
  const line = d3.line().x(d => x(d[0])).y(d => y(d[1])).curve(d3.curveMonotoneX);
  const starLayer = peaksSvg.append("g");
  const playhead = peaksSvg.append("line").attr("class", "playhead").attr("y1", pm.t).attr("y2", PH - pm.b);
  let starG = starLayer.selectAll("g");

  function bindPeaks() {
    const v = view();
    document.getElementById("peaks-title").textContent = v.regional ? `Overlapping peaks · ${v.name}` : "Overlapping peaks";
    const allY = v.stars.flatMap(s => s.points.map(p => p[1])).sort(d3.ascending);
    const yMax = Math.max(M.flagZ + 1, d3.quantile(allY, 0.995) || 1);   // one extreme season can't squash the rest
    y.domain([-1.5, Math.ceil(yMax + 0.5)]);
    yAxis.call(d3.axisLeft(y).ticks(6));
    flagLine.attr("y1", y(M.flagZ)).attr("y2", y(M.flagZ));
    flagText.attr("y", y(M.flagZ) - 4);
    starG = starLayer.selectAll("g.star").data(v.stars, s => s.id).join(enter => {
      const g = enter.append("g").attr("class", "star");
      g.append("path").attr("class", "curve");
      g.append("text").attr("class", "peak-label").attr("text-anchor", "middle");
      g.append("path").attr("class", "curve-hit");
      return g;
    });
    starG.selectAll(".pt").data(s => s.points).join("circle").attr("class", "pt")
      .attr("cx", d => x(d[0])).attr("cy", d => y(d[1])).attr("r", 2);
    starG.select(".curve").attr("d", s => line(s.curve)).raise();
    starG.select(".peak-label").attr("x", s => x(s.peak)).attr("y", s => y(s.height) - 6)
      .text(s => s.name.replace("Player ", "")).raise();
    starG.select(".curve-hit").attr("d", s => line(s.curve)).raise()
      .on("mousemove", (e, s) => { state.hoverStar = s.id; drawPeaksHighlight(); showTip(e, `<b>${s.name}</b><br>Peak ${s.peak.toFixed(1)} · window ${Math.round(s.window[0])}–${Math.round(s.window[1])}${s.league ? " · " + s.league : ""}`); })
      .on("mouseleave", () => { state.hoverStar = null; drawPeaksHighlight(); hideTip(); })
      .on("click", (e, s) => { setPlaying(false); setFrame(frameForSeason(s.peak)); });
    drawEras();
  }

  function drawEras() {
    const v = view();
    const g = bandG.selectAll("g").data(v.eras, d => state.region + state.metric + d.id).join(enter => {
      const gg = enter.append("g");
      gg.append("rect").attr("class", "era-band");
      gg.append("text").attr("class", "era-label");
      return gg;
    });
    g.select("rect").attr("x", d => x(d.start - 0.5)).attr("width", d => x(d.end + 0.5) - x(d.start - 0.5))
      .attr("y", pm.t).attr("height", PH - pm.t - pm.b).attr("rx", 3);
    g.select("text").attr("x", d => x(d.start - 0.5) + 4).attr("y", PH - pm.b - 6).text(d => `${d.start}–${d.end}`);
    const sy = d3.scaleLinear().domain([0, d3.max(v.series, d => d.strength) || 1]).range([PH - pm.b, PH - pm.b - 46]);
    strengthG.attr("d", d3.area().x(d => x(d.year)).y0(PH - pm.b).y1(d => sy(d.strength)).curve(d3.curveMonotoneX)(v.series));
  }

  const inPeak = (s, sp) => s.window[0] - 0.5 <= sp && sp <= s.window[1] + 0.5;
  function drawPeaksHighlight() {
    const sp = seasonPos(state.frame);
    starG.each(function (s) {
      const on = inPeak(s, sp), g = d3.select(this);
      g.select(".curve").classed("on", on).classed("hover", state.hoverStar === s.id);
      g.selectAll(".pt").classed("on", on);
      g.select(".peak-label").classed("on", on);
    });
  }

  // ---------- GROWTH ----------
  const growthEl = document.getElementById("growth");
  const sparks = [];
  (function buildGrowth() {
    const s = GROWTH.series;
    if (!s.length) {
      growthEl.innerHTML = `<div class="growth-empty">Growth data appears once the real-data steps have run.</div>`;
      return;
    }
    const metrics = [
      { name: "Nations playing internationals", key: "nations" },
      { name: "Nations that have ever played", key: "nationsTotal" },
      { name: "Internationals played", key: "matches" },
      { name: "Leagues with data here", key: "leagues" },
    ].map(m => ({ name: m.name, pts: s.map(d => [d.season, d[m.key]]) }));
    for (const [name, pts] of Object.entries(GROWTH.impact || {})) metrics.push({ name, pts, manual: true });
    document.getElementById("growth-hint").textContent = Object.keys(GROWTH.impact || {}).length
      ? "Includes your impact_manual.csv series" : "Add TV or attendance series in data/raw/impact_manual.csv";
    for (const m of metrics) {
      const row = document.createElement("div");
      row.className = "spark";
      row.innerHTML = `<span class="name">${m.name}</span><svg viewBox="0 0 600 42" preserveAspectRatio="none"></svg><span class="val"></span>`;
      growthEl.appendChild(row);
      const svg = d3.select(row.querySelector("svg"));
      const sx = d3.scaleLinear().domain([M.firstSeason - 0.5, M.lastSeason + 1]).range([0, 600]);
      const sy = d3.scaleLinear().domain([0, d3.max(m.pts, p => p[1]) || 1]).range([40, 3]);
      svg.append("path").attr("class", "area").attr("d", d3.area().x(p => sx(p[0])).y0(40).y1(p => sy(p[1]))(m.pts));
      svg.append("path").attr("class", "line").attr("d", d3.line().x(p => sx(p[0])).y(p => sy(p[1]))(m.pts));
      const ph = svg.append("line").attr("class", "ph").attr("y1", 0).attr("y2", 42);
      sparks.push({ m, ph, sx, val: row.querySelector(".val") });
    }
  })();
  function drawGrowth() {
    const sp = seasonPos(state.frame), season = seasonOf(state.frame);
    for (const s of sparks) {
      s.ph.attr("x1", s.sx(sp)).attr("x2", s.sx(sp));
      const p = s.m.pts.filter(q => q[0] <= season).pop();
      s.val.textContent = p ? d3.format(",")(Math.round(p[1])) : "—";
    }
  }

  // ---------- ERA TABLE ----------
  const table = d3.select("#era-table");
  function drawTable() {
    const v = view();
    document.getElementById("eras-title").textContent = v.regional ? `Comparing eras · ${v.name}` : "Comparing eras";
    const rows = v.regional
      ? v.eras.map(e => ({ start: e.start, end: e.end, length: e.length, stars: e.players.length, peakCount: e.peakCount }))
      : (data.eraTable || v.eras.map(e => ({ start: e.start, end: e.end, length: e.length, stars: e.players.length, peakCount: e.peakCount })));
    const impactKeys = v.regional ? [] : [...new Set(rows.flatMap(r => Object.keys(r.impact || {})))];
    const cols = [
      { h: "Era", f: r => `${r.start}–${r.end}` },
      { h: "Seasons", num: true, f: r => `<span class="mini-bar" style="width:${r.length * 3}px"></span>${r.length}` },
      { h: "Stars", num: true, f: r => r.stars },
      { h: "Peaking at once", num: true, f: r => r.peakCount ?? "—" },
    ];
    if (!v.regional && data.eraTable) {
      cols.push({ h: "Leagues", f: r => (r.leagues || []).join(", ") || "—" },
                { h: "Nations active", num: true, f: r => r.nationsActive ?? "—" },
                { h: "Tournaments", num: true, f: r => r.tournaments ?? "—" },
                { h: "Final crowd", num: true, f: r => r.finalAttendance ? d3.format(",")(r.finalAttendance) : "—" },
                ...impactKeys.map(key => ({ h: key, num: true, f: r => (r.impact || {})[key] ?? "—" })),
                { h: "Heart", f: r => (hubById[r.hub] || {}).name || "—" });
    }
    table.html("");
    table.append("thead").append("tr").selectAll("th").data(cols).join("th")
      .attr("class", c => c.num ? "num" : null).text(c => c.h);
    table.append("tbody").selectAll("tr").data(rows).join("tr")
      .on("click", (e, r) => { setPlaying(false); setFrame(frameForSeason(r.start)); })
      .selectAll("td").data(r => cols.map(c => ({ c, r }))).join("td")
      .attr("class", d => d.c.num ? "num" : null).html(d => d.c.f(d.r));
  }
  function markTableRow(season) {
    table.selectAll("tbody tr").classed("now", r => r.start <= season && season <= r.end);
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
    const v = view();
    const starById = Object.fromEntries(v.stars.map(s => [s.id, s]));
    const era = v.eras.find(e => e.start <= season && season <= e.end);
    const idx = era ? v.eras.indexOf(era) + 1 : 0;
    const total = map.hw.reduce((a, b) => a + b.w, 0) || 1;
    const topHubs = [...map.hw].sort((a, b) => b.w - a.w).filter(h => h.w > 0.05).slice(0, 4);
    const near = v.stars.filter(s => inPeak(s, sp)).sort((a, b) => b.height - a.height);
    const tours = map.tw.filter(t => f >= t.t.startFrame && f <= t.t.endFrame);

    let html = `<div class="d-date">${MONTHS[d.month - 1]} ${d.year}</div>
      <div class="d-season">Season ${seasonLabel(season)}${v.regional ? ` · ${v.name}` : ""}</div>`;

    if (state.selectedHub) {
      const h = hubById[state.selectedHub];
      const w = (map.hw.find(q => q.hub.id === h.id) || { w: 0 }).w;
      const listed = (data.hubPlayers && data.hubPlayers[h.id] && data.hubPlayers[h.id][String(season)]) ||
        data.stars.filter(s => s.clubs.some(c => c[0] === season && c[2] === h.id))
          .map(s => [s.name, clubAt(s, season) || "", null, null, true]);
      html += `<div class="d-block"><button class="d-close" id="close-hub" aria-label="Close">×</button>
        <div class="d-label">Selected hub</div><div class="d-big">${h.name}</div>
        <div class="d-note">${h.cities.join(", ")}</div>
        <div class="d-note" style="margin-top:6px">${Math.round((100 * w) / total)}% of club weight this moment</div>
        <div class="bar"><i style="width:${(100 * w) / total}%"></i></div>
        ${listed.length ? `<div class="d-label" style="margin-top:10px">Top scorers here, ${seasonLabel(season)}</div>
          <ul class="d-list">${listed.map(p => `<li><span>${p[4] ? "★ " : ""}${p[0]}</span><span class="where">${p[2] != null ? p[2] + " goals · " : ""}${p[1] || ""}</span></li>`).join("")}</ul>`
          : `<div class="d-note" style="margin-top:6px">No standout scorers here this season.</div>`}</div>`;
    }

    // Continental champions this season (older data files only have the European Cup)
    const champs = (data.champions && data.champions[String(season)]) ||
      (data.europe && data.europe[String(season)] ? { UCL: data.europe[String(season)] } : null);
    if (champs) {
      html += `<div class="d-block"><div class="d-label">Continental champions ${seasonLabel(season)}</div>
        ${Object.entries(champs).filter(([, c]) => c.winner).map(([comp, c]) =>
          `<div><b>🏆 ${c.winner[0]}</b> <span class="d-note">${CUPS[comp] || comp}${c.runner_up ? ` · beat ${c.runner_up[0]}` : ""}</span></div>`).join("")}</div>`;
    }

    const moments = MOMENTS[String(season)] || [];
    if (moments.length) {
      html += `<div class="d-block"><div class="d-label">Moments of ${seasonLabel(season)}</div>
        ${moments.slice(0, 6).map(m => `<div class="d-moment"><b>${m.title}</b><div class="d-note">${m.detail}</div></div>`).join("")}
        ${moments.length > 6 ? `<div class="d-note">+ ${moments.length - 6} more</div>` : ""}</div>`;
    }

    if (tours.length) {
      html += `<div class="d-block"><div class="d-label">Tournament under way</div>
        ${tours.map(t => `<div class="d-tour">${t.t.type} ${t.t.year} · ${t.t.host}</div>`).join("")}</div>`;
    }

    html += `<div class="d-block"><div class="d-label">Era · ${v.regional ? v.name : metricName[state.metric]}</div>`;
    if (era) {
      html += `<div class="d-big">Era ${idx}: ${era.start}–${era.end}</div>
        <div class="d-note">${era.length} seasons · up to ${era.peakCount} stars peaking together (${era.peakYear})${era.hub ? ` · heart: ${hubShort(era.hub)}` : ""}</div>
        <div class="d-note">Core: ${era.players.slice(0, 6).map(p => (starById[p] || {}).name || p).join(", ")}</div>`;
    } else {
      const next = v.eras.find(e => e.start > season), prev = [...v.eras].reverse().find(e => e.end < season);
      html += `<div class="d-big">Between eras</div><div class="d-note">${prev ? `After ${prev.start}–${prev.end}` : "Before the first era"}${next ? ` · next begins ${next.start}` : ""}</div>`;
    }
    html += `</div>`;

    html += `<div class="d-block"><div class="d-label">Heart of the game</div>
      ${topHubs.length ? topHubs.map(h => `<div style="margin-bottom:5px"><div style="display:flex;justify-content:space-between"><span>${h.hub.name}</span><span class="where d-note">${Math.round((100 * h.w) / total)}%</span></div><div class="bar"><i style="width:${(100 * h.w) / total}%"></i></div></div>`).join("") : `<div class="d-note">No star hubs active.</div>`}</div>`;

    html += `<div class="d-block"><div class="d-label">Near their peak</div>
      ${near.length ? `<ul class="d-list">${near.map(s => `<li><span>${s.name}</span><span class="where">${clubAt(s, season) || ""}</span></li>`).join("")}</ul>` : `<div class="d-note">Nobody in a peak window right now.</div>`}</div>`;

    if (!v.regional) {
      const agr = data.agreement.filter(a => a.a === state.metric || a.b === state.metric);
      html += `<div class="d-block"><div class="d-label">Do the measures agree?</div>
        ${agr.map(a => `<div class="d-note">${metricName[a.a === state.metric ? a.b : a.a]}: ${Math.round(a.jaccard * 100)}% overlap in era years (${a.from}–${a.to})</div>`).join("")}</div>`;
    }
    if (M.sample) html += `<div class="d-block d-note">${M.note}</div>`;
    desc.innerHTML = html;
    const c = document.getElementById("close-hub");
    if (c) c.onclick = () => { state.selectedHub = null; render(); };
  }

  // ---------- EXPORT: PNG and video clip of the map ----------
  function mapCss() {
    const cs = getComputedStyle(document.documentElement);
    const v = n => cs.getPropertyValue(n).trim();
    return `.sea{fill:${v("--sea")}}.graticule{fill:none;stroke:${v("--line")};stroke-width:.4px}
      .country{fill:${v("--land")};stroke:${v("--land-edge")};stroke-width:.5px}.country.c-none{fill:${v("--land-none")}}
      .country.c-play{fill:url(#hatch)}.hatch-bg{fill:${v("--land-none")}}.hatch-line{stroke:${v("--land")};stroke-width:1.6px}
      .hub{fill:${v("--hub-fill")};stroke:${v("--hub")};stroke-width:1.4px}.hub.selected{stroke-width:2.6px}
      .tour{fill:${v("--tour-fill")};stroke:${v("--tour")};stroke-width:1.6px;stroke-dasharray:4 3}
      .lead-ring{fill:none;stroke:${v("--lead")};stroke-width:2px}
      .hub-label{fill:${v("--ink")};paint-order:stroke;stroke:${v("--sea")};font-weight:600;font-family:system-ui,sans-serif}
      .tour-label{fill:${v("--tour")}}.map-date{font-family:Georgia,serif;font-size:34px;fill:${v("--ink")}}
      .map-sub{font-size:13px;fill:${v("--muted")};font-family:system-ui,sans-serif}
      .moment{fill:${v("--tour")};stroke:${v("--panel")};stroke-width:1px}.moment.club_final{fill:${v("--lead")}}`;
  }
  function mapImage(scale = 2) {
    const node = document.getElementById("map").cloneNode(true);
    node.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    node.setAttribute("width", MW * scale);
    node.setAttribute("height", MH * scale);
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = mapCss();
    node.insertBefore(style, node.firstChild);
    const src = new XMLSerializer().serializeToString(node);
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(src);
    });
  }
  const download = (href, name) => { const a = document.createElement("a"); a.href = href; a.download = name; a.click(); };
  const fileStamp = () => { const d = dateOf(state.frame); return `${d.year}-${String(d.month).padStart(2, "0")}`; };
  document.getElementById("export-png").addEventListener("click", async () => {
    const img = await mapImage(2);
    const c = document.createElement("canvas");
    c.width = MW * 2; c.height = MH * 2;
    c.getContext("2d").drawImage(img, 0, 0);
    download(c.toDataURL("image/png"), `eras-of-the-game-${fileStamp()}.png`);
  });

  const recBtn = document.getElementById("record");
  let recorder = null;
  recBtn.addEventListener("click", () => (recorder ? stopRecording() : startRecording()));
  function startRecording() {
    if (!window.MediaRecorder) { alertNote("This browser can't record video; try Chrome or Firefox."); return; }
    const c = document.createElement("canvas");
    c.width = MW * 2; c.height = MH * 2;
    const ctx = c.getContext("2d");
    const type = ["video/webm;codecs=vp9", "video/webm", "video/mp4"].find(t => MediaRecorder.isTypeSupported(t));
    const chunks = [];
    recorder = new MediaRecorder(c.captureStream(30), type ? { mimeType: type } : undefined);
    recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: recorder.mimeType });
      download(URL.createObjectURL(blob), `eras-of-the-game-${fileStamp()}.${blob.type.includes("mp4") ? "mp4" : "webm"}`);
      recorder = null;
      recBtn.classList.remove("on");
      recBtn.textContent = "● Record";
    };
    recorder.start(250);
    recBtn.classList.add("on");
    recBtn.textContent = "■ Stop";
    let busy = false;
    (function frame() {
      if (!recorder) return;
      if (!busy) {
        busy = true;
        mapImage(2).then(img => { ctx.drawImage(img, 0, 0); busy = false; }).catch(() => { busy = false; });
      }
      requestAnimationFrame(frame);
    })();
    if (!state.playing) setPlaying(true);
  }
  function stopRecording() { if (recorder && recorder.state !== "inactive") recorder.stop(); }
  function alertNote(msg) { document.getElementById("growth-hint").textContent = msg; }

  // ---------- CONTROLS ----------
  const scrub = document.getElementById("scrub");
  const clock = document.getElementById("clock");
  const playBtn = document.getElementById("play");
  scrub.max = N - 1;
  scrub.addEventListener("input", () => { setPlaying(false); setFrame(+scrub.value); });
  playBtn.addEventListener("click", () => setPlaying(!state.playing));
  document.getElementById("metric").addEventListener("change", e => { state.metric = e.target.value; bindPeaks(); drawTable(); render(); });
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
    else if (recorder) stopRecording();
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
    drawGrowth();
    playhead.attr("x1", x(seasonPos(f))).attr("x2", x(seasonPos(f)));
    const d = dateOf(f);
    clock.textContent = `${MONTHS[d.month - 1]} ${d.year}`;
    if (!fromTick || Math.floor(f) !== lastDesc) {
      drawDesc(map);
      markTableRow(seasonOf(f));
      lastDesc = Math.floor(f);
    }
    scrub.value = Math.floor(f);
  }

  // Measures the data can't support (e.g. assists in real data) are greyed out
  document.querySelectorAll("#metric option").forEach(o => {
    const ok = (data.eras[o.value] || []).length > 0;
    o.disabled = !ok;
    if (!ok) o.textContent += " (no data yet)";
  });

  // Deep links: ?t=2026-07&view=UEFA&metric=goals_raw&hub=hub7  (view=europe still works)
  const q = new URLSearchParams(location.search);
  if (q.get("metric") && data.eras[q.get("metric")]) {
    state.metric = q.get("metric");
    document.getElementById("metric").value = state.metric;
  }
  if (q.get("hub") && hubById[q.get("hub")]) state.selectedHub = q.get("hub");
  const t = /^(\d{4})-(\d{1,2})$/.exec(q.get("t") || "");
  state.frame = t ? Math.max(0, Math.min(N - 1, (+t[1] - y0) * 12 + (+t[2] - m0)))
                  : frameForSeason(data.stars.length ? data.stars[0].peak : M.firstSeason);
  const startView = { europe: "UEFA" }[q.get("view")] || q.get("view");
  regionBox.selectAll("button").classed("on", d => d === "world");
  bindPeaks();
  drawTable();
  if (startView && VIEWS[startView] && startView !== "world") setRegion(startView);
  else render();
  window.__eras = { state, setFrame, setPlaying, setRegion }; // handy for debugging
})();
