export const pct = (x: number | null | undefined, digits = 1) =>
  x == null ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(digits)}%`;

export const price = (x: number | null | undefined) => {
  if (x == null) return "—";
  const d = x >= 1000 ? 0 : x >= 1 ? 2 : 5;
  return x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
};

export const rupees = (x: number | null | undefined) =>
  x == null ? "—" : `${x < 0 ? "−" : "+"}₹${Math.abs(x).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export const r = (x: number | null | undefined) => (x == null ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(1)} R`);

export const ago = (iso?: string | null) => {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};

export const coin = (sym: string) => sym.replace(/USDT$/, "");

export const tone = (x: number | null | undefined) => (x == null ? "text-ink-3" : x >= 0 ? "text-up" : "text-down");
