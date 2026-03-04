import React, { useMemo, useState } from "react";

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (!Number.isFinite(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function Histogram({ bins, height = 260, xLabel = "P/E", yLabel = "Count" }) {
  const [hover, setHover] = useState(null);

  const maxCount = useMemo(() => (bins?.length ? Math.max(...bins.map((b) => b.count || 0)) : 0), [bins]);
  const chartH = height;
  const w = 900;
  const padL = 54;
  const padR = 18;
  const padT = 18;
  const padB = 44;
  const innerW = w - padL - padR;
  const innerH = chartH - padT - padB;

  const binCount = bins?.length || 0;
  const binW = binCount ? innerW / binCount : innerW;

  const yTicks = useMemo(() => {
    const steps = 4;
    const top = maxCount || 0;
    return Array.from({ length: steps + 1 }, (_, i) => Math.round((top * i) / steps));
  }, [maxCount]);

  function yForCount(count) {
    if (!maxCount) return padT + innerH;
    const pct = Math.max(0, Math.min(1, count / maxCount));
    return padT + (1 - pct) * innerH;
  }

  const xTicks = useMemo(() => {
    if (!bins?.length) return [];
    const first = bins[0];
    const last = bins[bins.length - 1];
    const minX = first?.from ?? null;
    const maxX = last?.to ?? null;
    const showEvery = bins.length > 8 ? 2 : 1;
    const ticks = [];
    for (let i = 0; i < bins.length; i += showEvery) {
      const b = bins[i];
      if (b?.from === undefined || b?.from === null) continue;
      ticks.push({ x: padL + i * binW, label: fmt(b.from) });
    }
    if (maxX !== null) ticks.push({ x: padL + bins.length * binW, label: fmt(maxX) });
    if (ticks.length === 0 && minX !== null && maxX !== null) {
      ticks.push({ x: padL, label: fmt(minX) });
      ticks.push({ x: padL + bins.length * binW, label: fmt(maxX) });
    }
    return ticks;
  }, [bins, binW]);

  return (
    <div className="histWrap">
      <svg className="histSvg" viewBox={`0 0 ${w} ${chartH}`} preserveAspectRatio="none" role="img" aria-label="Histogram">
        <defs>
          <marker id="arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" className="histAxisArrow" />
          </marker>
        </defs>

        {/* axes */}
        <line
          x1={padL}
          y1={padT + innerH}
          x2={w - padR}
          y2={padT + innerH}
          className="histAxis"
          markerEnd="url(#arrow)"
        />
        <line x1={padL} y1={padT + innerH} x2={padL} y2={padT} className="histAxis" markerEnd="url(#arrow)" />

        {/* axis labels */}
        <text x={w - padR} y={chartH - 10} className="histAxisLabel" textAnchor="end">
          {xLabel}
        </text>
        <text x={14} y={padT} className="histAxisLabel" textAnchor="start">
          {yLabel}
        </text>

        {/* y ticks + grid */}
        {yTicks.map((t) => {
          const y = yForCount(t);
          return (
            <g key={t}>
              <line x1={padL} y1={y} x2={w - padR} y2={y} className="histGrid" />
              <line x1={padL - 6} y1={y} x2={padL} y2={y} className="histAxis" />
              <text x={padL - 10} y={y} className="histTick" textAnchor="end" dominantBaseline="middle">
                {t}
              </text>
            </g>
          );
        })}

        {/* x ticks */}
        {xTicks.map((t, idx) => (
          <g key={`${t.label}-${idx}`}>
            <line x1={t.x} y1={padT + innerH} x2={t.x} y2={padT + innerH + 6} className="histAxis" />
            <text x={t.x} y={padT + innerH + 18} className="histTick" textAnchor="middle">
              {t.label}
            </text>
          </g>
        ))}

        {/* bars */}
        {(bins || []).map((b, i) => {
          const c = b.count || 0;
          const x = padL + i * binW;
          const y = yForCount(c);
          const h = padT + innerH - y;
          const isActive = hover === i;
          return (
            <g
              key={i}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              tabIndex={0}
            >
              <rect
                x={x + 1}
                y={y}
                width={Math.max(0, binW - 2)}
                height={h}
                className={isActive ? "histBar active" : "histBar"}
                rx="4"
              />
            </g>
          );
        })}
      </svg>

      <div className="histLegend">
        <div className="muted small">X: P/E bins • Y: number of holdings</div>
        <div className="muted small">
          {hover === null || !bins?.[hover]
            ? "Hover a bar to see the bin range and symbols."
            : `${bins[hover].label} → ${bins[hover].count} (${(bins[hover].symbols || []).join(", ")})`}
        </div>
      </div>
    </div>
  );
}
