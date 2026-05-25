// =====================================================================
// SVG line chart + parallel thermometer renderers.
// Pure functions: pass data, return SVG string. No deps.
// =====================================================================

const NS = 'http://www.w3.org/2000/svg';

function fmt(n) { return Number(n || 0).toLocaleString('en-US'); }

function fmtShort(n) {
  n = Number(n || 0);
  if (n >= 10000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  if (n >= 1000)  return (n / 1000).toFixed(2).replace(/\.?0+$/, '') + 'k';
  return String(Math.round(n));
}

function thermColor(pct, hasGoal) {
  if (!hasGoal) return 'var(--neutral, #7A8494)';
  if (pct >= 80) return 'var(--green, #4ADE80)';
  if (pct >= 40) return 'var(--orange, #FB923C)';
  return 'var(--red, #F87171)';
}

// =====================================================================
// LINE CHART + THERMOMETER (parallel layout)
//   series   - array of {date, count}, sorted ascending; count is cumulative-ready
//              (for phones we sum daily counts -> cumulative; for doors we
//              already store cumulative-by-day in history)
//   goal     - the goal value for this period (top of thermometer = goal)
//   hasGoal  - whether a goal is configured; if false, draw the chart without
//              the thermometer / scale to the chart's own max value
//   period   - 'week' | 'month' | 'total' (controls how we window the series)
//   today    - YYYY-MM-DD HST today (so we always render "through today")
// =====================================================================
function renderLineWithTherm({ series, goal, hasGoal, period, today, channel, windowRange, baseline = 0 }) {
  const W = 720, H = 320;
  const padL = 48, padR = 110, padT = 24, padB = 36;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;
  const thermW = 56;
  const thermX = W - padR + 18;
  const thermH = chartH;

  // Build cumulative series scoped to the current period window.
  // windowRange (when provided by the caller) is the authoritative [from, to]
  // pair from server-side compute; falls back to client-side last-N-days otherwise.
  const win = scopeSeries(series, period, today, windowRange);
  // For 'total' view we want the cumulative line to start at the baseline
  // (pre-launch knocks). For period views we want it to start at 0 (only
  // forward progress within the window matters).
  const startAt = period === 'total' ? baseline : 0;
  const cum = makeCumulative(win, startAt);

  // y-axis max = goal (when hasGoal), otherwise the cumulative max (with headroom).
  const dataMax = cum.length ? cum[cum.length - 1].cum : 0;
  const yMax = hasGoal && goal > 0 ? goal : Math.max(1, Math.ceil(dataMax * 1.15));

  // Map a (date, value) into SVG (x, y) coords. X is by date index, evenly spaced.
  const n = Math.max(2, cum.length);
  const xAt = (i) => padL + (chartW * i / (n - 1));
  const yAt = (v) => padT + chartH - (chartH * Math.min(v, yMax) / yMax);

  // Build the line path
  let path = '';
  let areaPath = '';
  if (cum.length === 0) {
    path = `M ${padL} ${padT + chartH} L ${padL + chartW} ${padT + chartH}`;
  } else if (cum.length === 1) {
    // single point: draw a horizontal line at that level across the window
    // so the chart reads as "we're holding steady at this value"
    const y = yAt(cum[0].cum);
    path = `M ${padL} ${y} L ${padL + chartW} ${y}`;
    areaPath = `M ${padL} ${padT + chartH} L ${padL} ${y} ` +
               `L ${padL + chartW} ${y} L ${padL + chartW} ${padT + chartH} Z`;
  } else {
    path = cum.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i)} ${yAt(p.cum)}`).join(' ');
    areaPath = `M ${xAt(0)} ${padT + chartH} ` +
               cum.map((p, i) => `L ${xAt(i)} ${yAt(p.cum)}`).join(' ') +
               ` L ${xAt(cum.length - 1)} ${padT + chartH} Z`;
  }

  // Thermometer fill height
  const filledVal = dataMax;
  const fillPct = yMax > 0 ? Math.min(100, (filledVal / yMax) * 100) : 0;
  const fillH = thermH * fillPct / 100;
  const fillY = padT + thermH - fillH;
  const therFill = thermColor(fillPct, hasGoal);

  // Y-axis labels (3 ticks: 0, mid, top)
  const ticks = [0, Math.round(yMax / 2), yMax];

  // X-axis labels: show every day for short windows (≤8 days), else pick up
  // to 7 evenly spaced. Using 7 instead of 6 means 7-day weeks get one label
  // per day with no skipped indices (the old `Math.min(6, 7)` skipped idx 3).
  const xLabels = [];
  if (cum.length === 1) {
    xLabels.push({ i: 0, label: shortDate(cum[0].date), x: padL + chartW });
  } else if (cum.length > 1) {
    const targetTicks = Math.min(7, cum.length);
    const seen = new Set();
    for (let t = 0; t < targetTicks; t++) {
      const idx = Math.round((cum.length - 1) * t / (targetTicks - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      xLabels.push({ i: idx, label: shortDate(cum[idx].date), x: xAt(idx) });
    }
  }

  const channelClass = `chart-${channel}`;

  return `
  <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="chart ${channelClass}">
    <!-- y-axis grid -->
    ${ticks.map(t => `
      <line x1="${padL}" y1="${yAt(t)}" x2="${padL + chartW}" y2="${yAt(t)}"
            class="chart-grid" />
      <text x="${padL - 8}" y="${yAt(t) + 4}" class="chart-y-label">${fmtShort(t)}</text>
    `).join('')}

    <!-- x-axis labels -->
    ${xLabels.map(x => `
      <text x="${x.x}" y="${H - 10}" class="chart-x-label" text-anchor="middle">${x.label}</text>
    `).join('')}

    <!-- area + line -->
    ${areaPath ? `<path d="${areaPath}" class="chart-area" />` : ''}
    <path d="${path}" class="chart-line" />

    <!-- last point dot (anchor at right edge when single-point so it reads as "today") -->
    ${cum.length ? `<circle cx="${cum.length === 1 ? padL + chartW : xAt(cum.length - 1)}"
                             cy="${yAt(cum[cum.length - 1].cum)}"
                             r="5" class="chart-dot" />` : ''}

    <!-- thermometer (parallel right) -->
    <g class="therm">
      <!-- track -->
      <rect x="${thermX}" y="${padT}" width="${thermW}" height="${thermH}"
            rx="${thermW/2}" class="therm-track" />
      <!-- fill -->
      <rect x="${thermX}" y="${fillY}" width="${thermW}" height="${fillH}"
            rx="${thermW/2}" fill="${therFill}" />
      <!-- top tick (goal) -->
      ${hasGoal ? `
        <line x1="${thermX - 6}" y1="${padT}" x2="${thermX + thermW + 6}" y2="${padT}"
              class="therm-tick" />
        <text x="${thermX + thermW + 10}" y="${padT + 4}" class="therm-tick-label">goal ${fmtShort(goal)}</text>
      ` : ''}
      <!-- current value: centered in fill when fill is tall enough; else above the fill -->
      ${(() => {
        const fillTooSmall = fillH < 28;
        const y = fillTooSmall
          ? Math.max(padT + 14, fillY - 6)            // just above the fill cap
          : fillY + Math.min(fillH / 2, 30) + 6;       // centered in fill (cap so it stays near top)
        const cls = fillTooSmall ? 'therm-current-outside' : 'therm-current';
        return `<text x="${thermX + thermW / 2}" y="${y}"
                      class="${cls}" text-anchor="middle">${fmtShort(filledVal)}</text>`;
      })()}
      <!-- percent below -->
      <text x="${thermX + thermW / 2}" y="${padT + thermH + 22}"
            class="therm-pct" text-anchor="middle">${hasGoal ? Math.round(fillPct) + '%' : '—'}</text>
    </g>
  </svg>`;
}

// =====================================================================
// Helpers
// =====================================================================
function scopeSeries(series, period, todayISO, windowRange) {
  // Prefer the explicit window from the server when present — keeps the
  // chart in sync with the server's count_week / count_month totals AND
  // makes the x-axis span the full selected period (even on dates with no
  // data yet, e.g. doors history only started 5/21 but the week is 5/18-5/24).
  if (windowRange && windowRange.length === 2) {
    return padSeriesToRange(series || [], windowRange[0], windowRange[1]);
  }
  if (!series || !series.length) return [];
  if (period === 'total') {
    return series.filter(p => p.date <= todayISO);
  }
  const today = new Date(todayISO + 'T00:00:00');
  const from = new Date(today);
  from.setDate(today.getDate() - (period === 'week' ? 6 : 29));
  const fromISO = from.toISOString().slice(0, 10);
  return series.filter(p => p.date >= fromISO && p.date <= todayISO);
}

// Return a series with one entry per day in [fromISO, toISO] inclusive.
// Existing series entries are preserved; missing dates get count: 0 so the
// chart's x-axis spans the entire selected window.
function padSeriesToRange(series, fromISO, toISO) {
  const byDate = new Map(series.map(p => [p.date, p]));
  const out = [];
  const cur = new Date(fromISO + 'T00:00:00');
  const end = new Date(toISO + 'T00:00:00');
  while (cur <= end) {
    const iso = cur.toISOString().slice(0, 10);
    out.push(byDate.get(iso) || { date: iso, count: 0 });
    cur.setDate(cur.getDate() + 1);
  }
  return out;
}

// Both phones and (new-style) doors series are per-day NEW counts.
// startAt is the baseline floor — added before summing, so the cumulative
// line begins at startAt and climbs.
function makeCumulative(series, startAt = 0) {
  if (!series.length) return [];
  let run = startAt;
  return series.map(p => { run += (p.count || 0); return { date: p.date, cum: run }; });
}

function shortDate(iso) {
  // "2026-05-19" -> "5/19"
  const [, m, d] = iso.split('-');
  return `${parseInt(m, 10)}/${parseInt(d, 10)}`;
}
