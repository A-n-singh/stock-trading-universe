import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { CandleData } from "../api";

const UP = "#1baf7a";
const DOWN = "#e5484d";
const GRID = "rgba(255,255,255,0.05)";
const TEXT = "#6f7886";

function baseChart(el: HTMLElement, height: number): IChartApi {
  return createChart(el, {
    height,
    layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: TEXT, fontFamily: "Inter, system-ui, sans-serif" },
    grid: { vertLines: { visible: false }, horzLines: { color: GRID } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: false },
    crosshair: { mode: 1 },
    autoSize: true,
  });
}

/** Candles + trend line + ▲ where the price rules say "buy". Hover shows values (crosshair). */
export function CandleChart({ data, height = 420 }: { data: CandleData; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = baseChart(ref.current, height);
    const last = data.candles.at(-1)?.close ?? 1;
    const precision = last >= 1000 ? 0 : last >= 1 ? 2 : 6;  // no ".00" on five-digit prices
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
      priceFormat: { type: "price", precision, minMove: 1 / 10 ** precision },
    });
    candles.setData(data.candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    const trend = chart.addSeries(LineSeries, { color: "#3987e5", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      priceFormat: { type: "price", precision, minMove: 1 / 10 ** precision } });
    trend.setData(data.trend.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    createSeriesMarkers(candles, data.buys.map((t) => ({
      time: t as UTCTimestamp, position: "belowBar" as const, shape: "arrowUp" as const, color: "#eda100", size: 1,
    })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, height]);
  return <div ref={ref} className="w-full" style={{ height }} />;
}

/** Step lines of running profit (R) with the hidden period shaded by a vertical marker line. */
export function ProfitChart({ curves, cutoff, height = 340 }: {
  curves: { name: string; color: string; points: { time: number; value: number }[] }[]; cutoff: string; height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = baseChart(ref.current, height);
    const cut = Math.floor(new Date(cutoff).getTime() / 1000);
    curves.forEach((c, i) => {
      const s = chart.addSeries(LineSeries, { color: c.color, lineWidth: 2, priceLineVisible: false, title: c.name });
      const pts = c.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));  // one point per day
      s.setData(pts);
      if (i === 0) {
        const at = pts.find((p) => p.time >= cut) ?? pts[pts.length - 1];
        if (at) createSeriesMarkers(s, [{ time: at.time, position: "aboveBar", shape: "square", color: "#aab2bf", text: "hidden period starts" }]);
      }
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [curves, cutoff, height]);
  return <div ref={ref} className="w-full" style={{ height }} />;
}

/** Tiny inline trend line for coin cards. */
export function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return null;
  const w = 120, h = 36;
  const lo = Math.min(...values), hi = Math.max(...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - lo) / (hi - lo || 1)) * (h - 4) - 2}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-9 w-[120px]" aria-hidden>
      <polyline points={pts} fill="none" stroke={up ? UP : DOWN} strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}
