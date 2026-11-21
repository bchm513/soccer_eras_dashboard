// Postable output: the map as a PNG, or a video clip recorded while it plays.
import { MW, MH } from "./map.js";

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

export function createExport(ctx) {
  const { state, time } = ctx;
  const stamp = () => { const d = time.dateOf(state.frame); return `${d.year}-${String(d.month).padStart(2, "0")}`; };

  document.getElementById("export-png").addEventListener("click", async () => {
    const img = await mapImage(2);
    const c = document.createElement("canvas");
    c.width = MW * 2; c.height = MH * 2;
    c.getContext("2d").drawImage(img, 0, 0);
    download(c.toDataURL("image/png"), `eras-of-the-game-${stamp()}.png`);
  });

  const btn = document.getElementById("record");
  let recorder = null;
  btn.addEventListener("click", () => (recorder ? stop() : start()));

  function start() {
    if (!window.MediaRecorder) {
      document.getElementById("growth-hint").textContent = "This browser can't record video; try Chrome or Firefox.";
      return;
    }
    const c = document.createElement("canvas");
    c.width = MW * 2; c.height = MH * 2;
    const g = c.getContext("2d");
    const type = ["video/webm;codecs=vp9", "video/webm", "video/mp4"].find(t => MediaRecorder.isTypeSupported(t));
    const chunks = [];
    recorder = new MediaRecorder(c.captureStream(30), type ? { mimeType: type } : undefined);
    recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: recorder.mimeType });
      download(URL.createObjectURL(blob), `eras-of-the-game-${stamp()}.${blob.type.includes("mp4") ? "mp4" : "webm"}`);
      recorder = null;
      btn.classList.remove("on");
      btn.textContent = "● Record";
    };
    recorder.start(250);
    btn.classList.add("on");
    btn.textContent = "■ Stop";
    let busy = false;
    (function frame() {
      if (!recorder) return;
      if (!busy) {
        busy = true;
        mapImage(2).then(img => { g.drawImage(img, 0, 0); busy = false; }).catch(() => { busy = false; });
      }
      requestAnimationFrame(frame);
    })();
    if (!state.playing) ctx.setPlaying(true);
  }

  function stop() { if (recorder && recorder.state !== "inactive") recorder.stop(); }
  return { stop, recording: () => recorder !== null };
}
