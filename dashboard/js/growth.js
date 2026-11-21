// Growth panel: sparklines for nations, matches, leagues and your own impact series.
export function createGrowth(ctx) {
  const { M, state, time, growth } = ctx;
  const el = document.getElementById("growth");
  const sparks = [];
  const s = growth.series;
  if (!s.length) {
    el.innerHTML = `<div class="growth-empty">Growth data appears once the real-data steps have run.</div>`;
    return { draw() {} };
  }
  const metrics = [
    { name: "Nations playing internationals", key: "nations" },
    { name: "Nations that have ever played", key: "nationsTotal" },
    { name: "Internationals played", key: "matches" },
    { name: "Leagues with data here", key: "leagues" },
  ].map(m => ({ name: m.name, pts: s.map(d => [d.season, d[m.key]]) }));
  for (const [name, pts] of Object.entries(growth.impact || {})) metrics.push({ name, pts, manual: true });
  document.getElementById("growth-hint").textContent = Object.keys(growth.impact || {}).length
    ? "Includes your impact_manual.csv series" : "Add TV or attendance series in data/manual/impact_manual.csv";
  for (const m of metrics) {
    const row = document.createElement("div");
    row.className = "spark";
    row.innerHTML = `<span class="name">${m.name}</span><svg viewBox="0 0 600 42" preserveAspectRatio="none"></svg><span class="val"></span>`;
    el.appendChild(row);
    const svg = d3.select(row.querySelector("svg"));
    const sx = d3.scaleLinear().domain([M.firstSeason - 0.5, M.lastSeason + 1]).range([0, 600]);
    const sy = d3.scaleLinear().domain([0, d3.max(m.pts, p => p[1]) || 1]).range([40, 3]);
    svg.append("path").attr("class", "area").attr("d", d3.area().x(p => sx(p[0])).y0(40).y1(p => sy(p[1]))(m.pts));
    svg.append("path").attr("class", "line").attr("d", d3.line().x(p => sx(p[0])).y(p => sy(p[1]))(m.pts));
    const ph = svg.append("line").attr("class", "ph").attr("y1", 0).attr("y2", 42);
    sparks.push({ m, ph, sx, val: row.querySelector(".val") });
  }

  function draw() {
    const sp = time.seasonPos(state.frame), season = time.seasonOf(state.frame);
    for (const k of sparks) {
      k.ph.attr("x1", k.sx(sp)).attr("x2", k.sx(sp));
      const p = k.m.pts.filter(q => q[0] <= season).pop();
      k.val.textContent = p ? d3.format(",")(Math.round(p[1])) : "—";
    }
  }
  return { draw };
}
