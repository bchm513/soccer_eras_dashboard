// Map panel: countries by stage of growth, club hubs, tournament spikes, the lead ring and moments.
import { lerp } from "./time.js";
import { showTip, hideTip } from "./tip.js";

export const MW = 960, MH = 520;
export const VIEWS = {
  world: [[-125, -45], [60, 68], [140, 30]],
  UEFA: [[-11, 35], [45, 62]], CONMEBOL: [[-82, -56], [-34, 12]], CONCACAF: [[-125, 7], [-60, 50]],
  AFC: [[45, -10], [150, 55]], CAF: [[-18, -35], [52, 37]], OFC: [[110, -48], [180, 0]],
};

export function createMap(ctx, world) {
  const { data, state, time } = ctx;
  const N = time.N;
  const growth = ctx.growth;
  const moments = data.moments || {};

  const tourSeries = data.tournaments.map(t => {
    const arr = new Float32Array(N);
    t.weights.forEach(([f, w]) => { arr[f] = w; });
    return { ...t, arr };
  });
  const hubWeights = f => data.hubs.map(h => ({ hub: h, w: lerp(data.clubWeights[h.id], f) }));
  const tourWeights = f => tourSeries.map(t => ({ t, w: lerp(t.arr, f) })).filter(d => d.w > 0.01);
  const maxW = Math.max(1e-6, ...Object.values(data.clubWeights).flat(),
                        ...data.tournaments.flatMap(t => t.weights.map(w => w[1])));

  const svg = d3.select("#map").attr("viewBox", `0 0 ${MW} ${MH}`);
  const hatch = svg.append("defs").append("pattern").attr("id", "hatch").attr("patternUnits", "userSpaceOnUse")
    .attr("width", 5).attr("height", 5).attr("patternTransform", "rotate(45)");
  hatch.append("rect").attr("class", "hatch-bg").attr("width", 5).attr("height", 5);
  hatch.append("line").attr("class", "hatch-line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 5);
  svg.append("rect").attr("class", "sea").attr("width", MW).attr("height", MH);

  const countries = topojson.feature(world, world.objects.countries);
  const projection = d3.geoNaturalEarth1();
  projection.fitExtent([[10, 10], [MW - 10, MH - 10]], { type: "MultiPoint", coordinates: VIEWS.world });
  const path = d3.geoPath(projection);
  const zoomLayer = svg.append("g");
  zoomLayer.append("path").datum(d3.geoGraticule10()).attr("class", "graticule").attr("d", path);
  const countryPaths = zoomLayer.append("g").selectAll("path").data(countries.features).join("path")
    .attr("class", "country").attr("d", path);
  const r = d3.scaleSqrt().domain([0, maxW]).range([0, 46]);
  const hubG = zoomLayer.append("g");
  const tourG = zoomLayer.append("g");
  const leadRing = zoomLayer.append("circle").attr("class", "lead-ring").attr("r", 0);
  const momentG = zoomLayer.append("g");
  const labelG = zoomLayer.append("g");
  const mapDate = svg.append("text").attr("class", "map-date").attr("x", 18).attr("y", 46);
  const mapSub = svg.append("text").attr("class", "map-sub").attr("x", 20).attr("y", 66);
  let k = 1;

  const zoom = d3.zoom().scaleExtent([1, 8]).on("zoom", e => {
    k = e.transform.k;
    zoomLayer.attr("transform", e.transform);
    draw(state.frame);
  });
  svg.call(zoom);
  function zoomTo(name) {
    const b = path.bounds({ type: "MultiPoint", coordinates: VIEWS[name] || VIEWS.world });
    const s = Math.min(8, 0.92 / Math.max((b[1][0] - b[0][0]) / MW, (b[1][1] - b[0][1]) / MH));
    const tx = MW / 2 - s * (b[0][0] + b[1][0]) / 2, ty = MH / 2 - s * (b[0][1] + b[1][1]) / 2;
    svg.transition().duration(700).call(zoom.transform,
      name === "world" ? d3.zoomIdentity : d3.zoomIdentity.translate(tx, ty).scale(s));
  }

  // Countries: not yet playing internationals / playing without league data / league data
  let lastCountrySeason = null;
  function drawCountries(season) {
    if (season === lastCountrySeason || !Object.keys(growth.countries).length) return;
    lastCountrySeason = season;
    countryPaths.attr("class", f => {
      const name = f.properties.name, first = growth.countries[name], cov = growth.leagueCoverage[name];
      if (first == null || season < first) return "country c-none";
      if (cov && cov[0] <= season && season <= cov[1]) return "country c-league";
      return "country c-play";
    });
  }
  countryPaths.on("mousemove", (e, f) => {
    const name = f.properties.name, first = growth.countries[name], cov = growth.leagueCoverage[name];
    if (first == null && !cov) return hideTip();
    showTip(e, `<b>${name}</b>${first != null ? `<br>First international: ${first}` : ""}` +
               (cov ? `<br>League data: ${cov[0]}–${cov[1]}` : "<br>No league data yet"));
  }).on("mouseleave", hideTip);

  function draw(f) {
    const hw = hubWeights(f);
    const tw = tourWeights(f);
    const xy = d => projection([d.lon, d.lat]);
    const rad = w => Math.max(r(w), w > 0.05 ? 2 : 0) / Math.sqrt(k);   // readable minimum when zoomed
    drawCountries(time.seasonOf(f));

    hubG.selectAll("circle").data(hw, d => d.hub.id).join("circle")
      .attr("class", d => "hub" + (state.selectedHub === d.hub.id ? " selected" : ""))
      .attr("cx", d => xy(d.hub)[0]).attr("cy", d => xy(d.hub)[1])
      .attr("r", d => rad(d.w))
      .on("mousemove", (e, d) => showTip(e, `<b>${d.hub.name}</b><br>${d.hub.cities.join(", ")}`))
      .on("mouseleave", hideTip)
      .on("click", (e, d) => { ctx.setPlaying(false); state.selectedHub = d.hub.id; ctx.render(); });

    tourG.selectAll("circle").data(tw, d => d.t.id).join("circle")
      .attr("class", "tour")
      .attr("cx", d => xy(d.t)[0]).attr("cy", d => xy(d.t)[1])
      .attr("r", d => rad(d.w))
      .on("mousemove", (e, d) => showTip(e, `<b>${d.t.type} ${d.t.year}</b><br>${d.t.host}`))
      .on("mouseleave", hideTip)
      .on("click", () => ctx.setPlaying(false));

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
    const mo = (moments[String(time.seasonOf(f))] || []).filter(m => m.lat != null && m.lon != null);
    momentG.selectAll("path").data(mo, m => m.title).join("path")
      .attr("class", m => "moment " + m.kind)
      .attr("transform", m => { const [px, py] = xy(m); return `translate(${px},${py}) scale(${1 / Math.sqrt(k)})`; })
      .attr("d", d3.symbol(d3.symbolDiamond, 60)())
      .on("mousemove", (e, m) => showTip(e, `<b>${m.title}</b><br>${m.detail}`))
      .on("mouseleave", hideTip)
      .on("click", () => ctx.setPlaying(false));

    mapDate.text(time.dateLabel(f));
    mapSub.text(lead.w > 0.05 ? `Heart of the game: ${lead.name}` : "");
    return { hw, tw, lead };
  }

  return { draw, zoomTo };
}
