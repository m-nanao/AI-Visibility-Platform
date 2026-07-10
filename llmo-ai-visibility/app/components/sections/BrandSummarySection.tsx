import Card from "../Card";
import type { BrandSummary } from "../../lib/types";

export default function BrandSummarySection({
  summary,
}: {
  summary: BrandSummary;
}) {
  const { positive, neutral, negative } = summary.sentimentBreakdown;

  return (
    <Card
      title="1. ブランド認知サマリー"
      description={`「${summary.brandName}」のAIプラットフォーム上での認知状況`}
    >
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">認知スコア</p>
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {summary.visibilityScore}
            <span className="text-sm font-normal text-zinc-400"> / 100</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">総言及数</p>
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {summary.totalMentions}
          </p>
        </div>
        <div className="col-span-2">
          <p className="text-xs text-zinc-500 dark:text-zinc-400">主要プラットフォーム</p>
          <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">
            {summary.topPlatforms.join(" / ")}
          </p>
        </div>
      </div>

      <div className="mt-5">
        <p className="mb-1 text-xs text-zinc-500 dark:text-zinc-400">
          センチメント内訳
        </p>
        <div className="flex h-2 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
          <div className="bg-emerald-500" style={{ width: `${positive}%` }} />
          <div className="bg-zinc-400" style={{ width: `${neutral}%` }} />
          <div className="bg-rose-500" style={{ width: `${negative}%` }} />
        </div>
        <div className="mt-2 flex gap-4 text-xs text-zinc-500 dark:text-zinc-400">
          <span>ポジティブ {positive}%</span>
          <span>ニュートラル {neutral}%</span>
          <span>ネガティブ {negative}%</span>
        </div>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
        {summary.summaryText}
      </p>
    </Card>
  );
}
