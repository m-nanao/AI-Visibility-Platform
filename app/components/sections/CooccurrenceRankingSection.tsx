import Card from "../Card";
import { trendStyles } from "../../lib/badge-styles";
import type { CooccurrenceKeyword } from "../../lib/types";

export default function CooccurrenceRankingSection({
  items,
}: {
  items: CooccurrenceKeyword[];
}) {
  const maxCount = Math.max(...items.map((item) => item.count));

  return (
    <Card
      title="2. 共起語ランキング"
      description="ブランド名と一緒に言及されやすいキーワード"
    >
      <ol className="flex flex-col gap-3">
        {items.map((item, index) => (
          <li key={item.keyword} className="flex items-center gap-3">
            <span className="w-5 shrink-0 text-sm font-medium text-zinc-400">
              {index + 1}
            </span>
            <div className="flex-1">
              <div className="mb-1 flex items-center justify-between text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">
                  {item.keyword}
                </span>
                <span className="flex items-center gap-2 text-zinc-500 dark:text-zinc-400">
                  {item.count}件
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs ${trendStyles[item.trend].className}`}
                  >
                    {trendStyles[item.trend].label}
                  </span>
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-zinc-100 dark:bg-zinc-800">
                <div
                  className="h-1.5 rounded-full bg-zinc-700 dark:bg-zinc-300"
                  style={{ width: `${(item.count / maxCount) * 100}%` }}
                />
              </div>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}
