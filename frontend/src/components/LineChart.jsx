import React, { useMemo } from "react";

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (!Number.isFinite(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export default function LineChart({ points, height = 260, xLabel = "Time", yLabel = "Value" }) {
  const w = 900;
  const h = height;
  const padL = 56;
  const padR = 18;
  const padT = 18;
  const padB = 44;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  const ys = useMemo(() => (points || []).map((p) => Number(p.y)).filter((v) => Number.isFinite(v)), [points]);
  const minY = ys.length ? Math.min(...ys) : 0;
  const maxY = ys.length ? Math.max(...ys) : 1;
  const spanY = maxY - minY || 1;

  const pathD = useMemo(() => {
    if (!points || points.length < 2) return "";
    const n = points.length;
    return points
      .map((p, i) => {
        const x = padL + (i / (n - 1)) * innerW;
        const y = padT + (1 - (Number(p.y) - minY) / spanY) * innerH;
        return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
  }, [points, innerW, innerH, minY, spanY]);

  const yTicks = useMemo(() => {
    const steps = 4;
    return Array.from({ length: steps + 1 }, (_, i) => minY + (spanY * i) / steps);
  }, [minY, spanY]);

  const xTickLabels = useMemo(() => {
    if (!points || points.length === 0) return [];
    const idxs = [0, Math.floor(points.length / 2), points.length - 1].filter((v, i, a) => a.indexOf(v) === i);
    return idxs.map((i) => ({ i, label: points[i]?.xLabel || "" }));
  }, [points]);

  return (
    <div className="histWrap">
      <svg className="histSvg" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Line chart">
        <defs>
          <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(124, 92, 255, 0.95)" />
            <stop offset="100%" stopColor="rgba(48, 209, 88, 0.55)" />
          </linearGradient>
        </defs>

        {/* axes */}
        <line x1={padL} y1={padT + innerH} x2={w - padR} y2={padT + innerH} className="histAxis" />
        <line x1={padL} y1={padT} x2={padL} y2={padT + innerH} className="histAxis" />

        {/* labels */}
        <text x={w - padR} y={h - 10} className="histAxisLabel" textAnchor="end">
          {xLabel}
        </text>
        <text x={14} y={padT} className="histAxisLabel" textAnchor="start">
          {yLabel}
        </text>

        {/* y ticks */}
        {yTicks.map((t) => {
          const y = padT + (1 - (t - minY) / spanY) * innerH;
          return (
            <g key={t}>
              <line x1={padL} y1={y} x2={w - padR} y2={y} className="histGrid" />
              <text x={padL - 10} y={y} className="histTick" textAnchor="end" dominantBaseline="middle">
                {fmt(t)}
              </text>
            </g>
          );
        })}

        {/* x ticks */}
        {xTickLabels.map((t) => {
          const n = points.length;
          const x = padL + (t.i / (n - 1)) * innerW;
          return (
            <g key={t.i}>
              <line x1={x} y1={padT + innerH} x2={x} y2={padT + innerH + 6} className="histAxis" />
              <text x={x} y={padT + innerH + 18} className="histTick" textAnchor="middle">
                {t.label}
              </text>
            </g>
          );
        })}

        {/* line */}
        {pathD ? <path d={pathD} fill="none" stroke="url(#lineGrad)" strokeWidth="3" /> : null}
      </svg>
    </div>
  );
}

