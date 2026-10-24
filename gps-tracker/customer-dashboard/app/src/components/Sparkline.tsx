import { useState } from 'react';
import classes from './Sparkline.module.css';

/** A small trend line for a KPI card: muted line, the latest point in the accent colour, a tooltip per point on hover. */
export function Sparkline({ values, labels, format, summary }: {
  values: number[]; labels: string[]; format: (v: number) => string; summary: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (values.length < 2) return null;
  const W = 100, H = 36, PAD = 5;
  const max = Math.max(...values), min = Math.min(...values, 0);
  const x = (i: number) => PAD + (i * (W - PAD * 2)) / (values.length - 1);
  const y = (v: number) => (max === min ? H / 2 : H - PAD - ((v - min) * (H - PAD * 2)) / (max - min));
  const last = values.length - 1;
  const shown = hover ?? last;
  return (
    <div className={classes.root} role="img" aria-label={summary}
         onMouseMove={(e) => {
           const r = e.currentTarget.getBoundingClientRect();
           const i = Math.round(((e.clientX - r.left) / r.width * W - PAD) / ((W - PAD * 2) / last));
           setHover(Math.max(0, Math.min(last, i)));
         }}
         onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className={classes.svg} aria-hidden>
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} className={classes.cross} vectorEffect="non-scaling-stroke" />}
        <polyline points={values.map((v, i) => `${x(i)},${y(v)}`).join(' ')} className={classes.line} vectorEffect="non-scaling-stroke" />
      </svg>
      {/* Dots as HTML so they stay round when the line stretches with the card */}
      <span className={classes.dot} data-current={shown === last || undefined}
            style={{ left: `${x(shown)}%`, top: `${(y(values[shown]) / H) * 100}%` }} />
      {hover != null && (
        <span className={classes.tip} style={{ left: `${Math.min(80, Math.max(20, x(hover)))}%` }}>
          {labels[hover]}: <b>{format(values[hover])}</b>
        </span>
      )}
    </div>
  );
}
