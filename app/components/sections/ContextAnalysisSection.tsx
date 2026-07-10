import Card from "../Card";
import { sentimentStyles } from "../../lib/badge-styles";
import type { ContextAnalysisItem } from "../../lib/types";

export default function ContextAnalysisSection({
  items,
}: {
  items: ContextAnalysisItem[];
}) {
  return (
    <Card
      title="3. 文脈分析"
      description="ブランドがどのような文脈で語られているか"
    >
      <div className="flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800">
        {items.map((item) => (
          <div key={item.context} className="py-3 first:pt-0 last:pb-0">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                {item.context}
              </h3>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${sentimentStyles[item.sentiment].className}`}
              >
                {sentimentStyles[item.sentiment].label}
              </span>
            </div>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              {item.description}
            </p>
            <p className="mt-2 rounded-md bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-800/60 dark:text-zinc-400">
              {item.exampleQuote}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
}
