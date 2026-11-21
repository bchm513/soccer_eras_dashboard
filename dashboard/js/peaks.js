// Peaks panel: every star's career curve, era bands, era strength, and the playhead.
import { showTip, hideTip } from "./tip.js";

const PW = 1200, PH = 330, pm = { t: 26, r: 18, b: 28, l: 40 };

export const inPeak = (s, sp) => s.window[0] - 0.5 <= sp && sp <= s.window[1] + 0.5;

export function createPeaks(ctx) {
  const { M, state, time } = ctx;
  const svg = d3.select("#peaks").attr("viewBox", `0 0 ${PW} ${PH}`);
  const x = d3.scaleLinear().domain([M.firstSeason - 0.5, M.lastSeason + 1]).range([pm.l, PW - pm.r]);
  const y = d3.scaleLinear().range([PH - pm.b, pm.t]).clamp(true);
  const bandG = svg.append("g");
  const strengthG = svg.append("path").attr("class", "strength");
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${PH - pm.b})`)
    .call(d3.axisBottom(x).ticks(16).tickFormat(d3.format("d")));
  const yAxis = svg.append("g").attr("class", "axis").attr("transform", `translate(${pm.l},0)`);
  svg.append("text").attr("x", pm.l + 4).attr("y", pm.t - 10).attr("class", "peak-label")
    .text("Output vs league average (z)");
  const flagLine = svg.append("line").attr("class", "flag-line").attr("x1", pm.l).attr("x2", PW - pm.r);
  const flagText = svg.append("text").attr("class", "peak-label").attr("x", PW - pm.r - 4).attr("text-anchor", "end")
    .text(`star threshold z = ${M.flagZ}`);
  const line = d3.line().x(d => x(d[0])).y(d => y(d[1])).curve(d3.curveMonotoneX);
  const starLayer = svg.append("g");
  const playhead = svg.append("line").attr("class", "playhead").attr("y1", pm.t).attr("y2", PH - pm.b);
  let starG = starLayer.selectAll("g");

  function bind() {
    const v = ctx.view();
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
      .on("mousemove", (e, s) => {
        state.hoverStar = s.id;
        highlight();
        showTip(e, `<b>${s.name}</b><br>Peak ${s.peak.toFixed(1)} · window ${Math.round(s.window[0])}–${Math.round(s.window[1])}${s.league ? " · " + s.league : ""}`);
      })
      .on("mouseleave", () => { state.hoverStar = null; highlight(); hideTip(); })
      .on("click", (e, s) => { ctx.setPlaying(false); ctx.setFrame(time.frameForSeason(s.peak)); });
    drawEras(v);
  }

  function drawEras(v) {
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

  function highlight() {
    const sp = time.seasonPos(state.frame);
    starG.each(function (s) {
      const on = inPeak(s, sp), g = d3.select(this);
      g.select(".curve").classed("on", on).classed("hover", state.hoverStar === s.id);
      g.selectAll(".pt").classed("on", on);
      g.select(".peak-label").classed("on", on);
    });
  }

  function draw(f) {
    highlight();
    playhead.attr("x1", x(time.seasonPos(f))).attr("x2", x(time.seasonPos(f)));
  }

  return { bind, draw };
}
