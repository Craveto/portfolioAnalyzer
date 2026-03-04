import React, { useMemo } from "react";

function clamp01(v) {
  if (!Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(1, v));
}

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (!Number.isFinite(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function ScatterPlot({
  title,
  subtitle,
  points = [],
  height = 280,
  xLabel = "X",
  yLabel = "Y",
  xTickSuffix = "",
  yTickSuffix = "",
  colors = null,
  mono = false
}) {
  const { plotPoints, domain } = useMemo(() => {
    const pts = (points || [])
      .map((p) => ({
        x: Number(p.x),
        y: Number(p.y),
        r: Number(p.r),
        label: p.label || "",
        color: p.color || null
      }))
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));

    if (!pts.length) {
      return { plotPoints: [], domain: { minX: 0, maxX: 1, minY: 0, maxY: 1 } };
    }

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const p of pts) {
      minX = Math.min(minX, p.x);
      maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y);
      maxY = Math.max(maxY, p.y);
    }

    // pad domain a bit so points aren't glued to edges
    const padX = (maxX - minX) * 0.08 || 1;
    const padY = (maxY - minY) * 0.08 || 1;
    minX -= padX;
    maxX += padX;
    minY -= padY;
    maxY += padY;

    return { plotPoints: pts, domain: { minX, maxX, minY, maxY } };
  }, [points]);

  const viewW = 820;
  const viewH = 320;
  const padL = 54;
  const padR = 18;
  const padT = 16;
  const padB = 44;
  const innerW = viewW - padL - padR;
  const innerH = viewH - padT - padB;

  const xScale = (x) => {
    const t = (x - domain.minX) / (domain.maxX - domain.minX || 1);
    return padL + clamp01(t) * innerW;
  };
  const yScale = (y) => {
    const t = (y - domain.minY) / (domain.maxY - domain.minY || 1);
    return padT + (1 - clamp01(t)) * innerH;
  };

  const ticks = 5;
  const xTicks = Array.from({ length: ticks }, (_, i) => domain.minX + (i / (ticks - 1)) * (domain.maxX - domain.minX));
  const yTicks = Array.from({ length: ticks }, (_, i) => domain.minY + (i / (ticks - 1)) * (domain.maxY - domain.minY));

  const fallbackColors = colors && colors.length ? colors : ["var(--accent1)", "var(--accent2)", "var(--accent3)", "#60a5fa", "#f59e0b"];

  return (
    <div className="chartCard">
      <div className="chartHead">
        <div>
          <div className={mono ? "strong mono" : "strong"}>{title}</div>
          {subtitle ? <div className="muted small">{subtitle}</div> : null}
        </div>
      </div>

      <div
        className="chartWrap"
        style={{ height, position: "relative" }}
      >
        {plotPoints.length === 0 ? <div className="muted">Not enough data points.</div> : null}
        <svg
          viewBox={`0 0 ${viewW} ${viewH}`}
          width="100%"
          height="100%"
          role="img"
          aria-label={title}
          style={{ display: "block" }}
        >
          {/* grid */}
          {xTicks.map((t, i) => (
            <g key={`xg${i}`}>
              <line x1={xScale(t)} y1={padT} x2={xScale(t)} y2={padT + innerH} stroke="rgba(255,255,255,0.06)" />
              <text x={xScale(t)} y={padT + innerH + 18} fill="rgba(232,238,252,0.65)" fontSize="11" textAnchor="middle">
                {fmt(t)}
                {xTickSuffix}
              </text>
            </g>
          ))}
          {yTicks.map((t, i) => (
            <g key={`yg${i}`}>
              <line x1={padL} y1={yScale(t)} x2={padL + innerW} y2={yScale(t)} stroke="rgba(255,255,255,0.06)" />
              <text x={padL - 10} y={yScale(t) + 4} fill="rgba(232,238,252,0.65)" fontSize="11" textAnchor="end">
                {fmt(t)}
                {yTickSuffix}
              </text>
            </g>
          ))}

          {/* axes labels */}
          <text x={padL + innerW / 2} y={viewH - 10} fill="rgba(232,238,252,0.8)" fontSize="12" textAnchor="middle">
            {xLabel}
          </text>
          <text
            x={14}
            y={padT + innerH / 2}
            fill="rgba(232,238,252,0.8)"
            fontSize="12"
            textAnchor="middle"
            transform={`rotate(-90 14 ${padT + innerH / 2})`}
          >
            {yLabel}
          </text>

          {/* points */}
          {plotPoints.map((p, idx) => {
            const c = p.color || fallbackColors[idx % fallbackColors.length];
            const r = Number.isFinite(p.r) ? Math.max(2.8, Math.min(9.5, p.r)) : 4.2;
            return (
              <circle
                key={idx}
                cx={xScale(p.x)}
                cy={yScale(p.y)}
                r={r}
                fill={c}
                fillOpacity="0.92"
                stroke="rgba(0,0,0,0.35)"
                strokeWidth="1"
              >
                {p.label ? <title>{p.label}</title> : null}
              </circle>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
