// The shared monthly timeline: frame <-> date <-> season.
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function makeTime(meta) {
  const [y0, m0] = meta.start.split("-").map(Number);
  const N = meta.frames;
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
  const frameForMonth = (y, m) => Math.max(0, Math.min(N - 1, (y - y0) * 12 + (m - m0)));
  const dateLabel = f => { const d = dateOf(f); return `${MONTHS[d.month - 1]} ${d.year}`; };
  return { N, dateOf, seasonPos, seasonOf, seasonLabel, frameForSeason, frameForMonth, dateLabel };
}

export const lerp = (arr, f) => {
  const i = Math.floor(f), j = Math.min(i + 1, arr.length - 1), t = f - i;
  return arr[i] * (1 - t) + arr[j] * t;
};
