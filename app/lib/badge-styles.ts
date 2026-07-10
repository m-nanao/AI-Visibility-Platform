import type { Priority, Sentiment, Trend } from "./types";

export const trendStyles: Record<Trend, { label: string; className: string }> = {
  up: { label: "↑ 上昇", className: "text-emerald-700 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950" },
  down: { label: "↓ 下降", className: "text-rose-700 bg-rose-50 dark:text-rose-400 dark:bg-rose-950" },
  flat: { label: "→ 横ばい", className: "text-zinc-600 bg-zinc-100 dark:text-zinc-400 dark:bg-zinc-800" },
};

export const sentimentStyles: Record<Sentiment, { label: string; className: string }> = {
  positive: { label: "ポジティブ", className: "text-emerald-700 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950" },
  neutral: { label: "ニュートラル", className: "text-zinc-600 bg-zinc-100 dark:text-zinc-400 dark:bg-zinc-800" },
  negative: { label: "ネガティブ", className: "text-rose-700 bg-rose-50 dark:text-rose-400 dark:bg-rose-950" },
};

export const priorityStyles: Record<Priority, { label: string; className: string }> = {
  high: { label: "優先度: 高", className: "text-rose-700 bg-rose-50 dark:text-rose-400 dark:bg-rose-950" },
  medium: { label: "優先度: 中", className: "text-amber-700 bg-amber-50 dark:text-amber-400 dark:bg-amber-950" },
  low: { label: "優先度: 低", className: "text-zinc-600 bg-zinc-100 dark:text-zinc-400 dark:bg-zinc-800" },
};
