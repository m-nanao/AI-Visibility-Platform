import Card from "../Card";
import type { AIOverviewComparisonItem } from "../../lib/types";

export default function AIOverviewComparisonSection({
  items,
}: {
  items: AIOverviewComparisonItem[];
}) {
  return (
    <Card
      title="4. AI Overview比較"
      description="主要AIサービスにおける掲載・言及状況の比較"
    >
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              <th className="py-2 pr-4 font-medium">プラットフォーム</th>
              <th className="py-2 pr-4 font-medium">掲載</th>
              <th className="py-2 pr-4 font-medium">順位</th>
              <th className="py-2 font-medium">概要</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.platform}
                className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60"
              >
                <td className="py-2.5 pr-4 font-medium text-zinc-800 dark:text-zinc-200">
                  {item.platform}
                </td>
                <td className="py-2.5 pr-4">
                  {item.mentioned ? (
                    <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400">
                      あり
                    </span>
                  ) : (
                    <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                      なし
                    </span>
                  )}
                </td>
                <td className="py-2.5 pr-4 text-zinc-600 dark:text-zinc-400">
                  {item.rank ? `${item.rank}位` : "—"}
                </td>
                <td className="py-2.5 text-zinc-600 dark:text-zinc-400">
                  {item.summary}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
