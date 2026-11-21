// Era comparison table: one row per era; click to jump there.
export function createTable(ctx) {
  const { data, time } = ctx;
  const table = d3.select("#era-table");
  const basic = e => ({ start: e.start, end: e.end, length: e.length, stars: e.players.length, peakCount: e.peakCount });

  function draw() {
    const v = ctx.view();
    document.getElementById("eras-title").textContent = v.regional ? `Comparing eras · ${v.name}` : "Comparing eras";
    const full = !v.regional && data.eraTable;
    const rows = full ? data.eraTable : v.eras.map(basic);
    const impactKeys = full ? [...new Set(rows.flatMap(r => Object.keys(r.impact || {})))] : [];
    const cols = [
      { h: "Era", f: r => `${r.start}–${r.end}` },
      { h: "Seasons", num: true, f: r => `<span class="mini-bar" style="width:${r.length * 3}px"></span>${r.length}` },
      { h: "Stars", num: true, f: r => r.stars },
      { h: "Peaking at once", num: true, f: r => r.peakCount ?? "—" },
    ];
    if (full) {
      cols.push({ h: "Leagues", f: r => (r.leagues || []).join(", ") || "—" },
                { h: "Nations active", num: true, f: r => r.nationsActive ?? "—" },
                { h: "Tournaments", num: true, f: r => r.tournaments ?? "—" },
                { h: "Final crowd", num: true, f: r => r.finalAttendance ? d3.format(",")(r.finalAttendance) : "—" },
                ...impactKeys.map(key => ({ h: key, num: true, f: r => (r.impact || {})[key] ?? "—" })),
                { h: "Heart", f: r => (ctx.hubById[r.hub] || {}).name || "—" });
    }
    table.html("");
    table.append("thead").append("tr").selectAll("th").data(cols).join("th")
      .attr("class", c => c.num ? "num" : null).text(c => c.h);
    table.append("tbody").selectAll("tr").data(rows).join("tr")
      .on("click", (e, r) => { ctx.setPlaying(false); ctx.setFrame(time.frameForSeason(r.start)); })
      .selectAll("td").data(r => cols.map(c => ({ c, r }))).join("td")
      .attr("class", d => d.c.num ? "num" : null).html(d => d.c.f(d.r));
  }

  const mark = season => table.selectAll("tbody tr").classed("now", r => r.start <= season && season <= r.end);
  return { draw, mark };
}
