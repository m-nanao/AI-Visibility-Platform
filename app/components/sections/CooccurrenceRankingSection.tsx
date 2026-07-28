import Card from "../Card";
import { trendStyles } from "../../lib/badge-styles";
import {
  getAnalysisSourceBreakdownDisplay,
  getCommonCrawlAnalyzedPagesDisplay,
  getCommonCrawlProviderDisplay,
  getCooccurrenceUnavailableMessage,
  getUrlFetchSummary,
} from "../../lib/meta-label";
import type { AnalysisMeta, CooccurrenceKeyword } from "../../lib/types";

export default function CooccurrenceRankingSection({
  items,
  meta,
}: {
  items: CooccurrenceKeyword[];
  meta: AnalysisMeta;
}) {
  const unavailableMessage = getCooccurrenceUnavailableMessage(meta);
  const sourceBreakdown = getAnalysisSourceBreakdownDisplay(meta);
  const urlFetchSummary = getUrlFetchSummary(meta);
  const commonCrawlProvider = getCommonCrawlProviderDisplay(meta);
  const commonCrawlAnalyzedPages = getCommonCrawlAnalyzedPagesDisplay(meta);
  const maxCount = items.length > 0 ? Math.max(...items.map((item) => item.count)) : 0;

  return (
    <Card
      title="2. 共起語ランキング"
      description="ブランド名と一緒に言及されやすいキーワード"
    >
      {sourceBreakdown && (
        <p className="mb-1 text-xs text-zinc-500 dark:text-zinc-400">
          分析ソース: {sourceBreakdown}
        </p>
      )}

      {urlFetchSummary && (
        <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
          {urlFetchSummary}
        </p>
      )}

      {/* Common Crawl「補完」の状態は、この結果に使われたDocument[]の
          出典に関する軽い状態表示であり、大きなカードは持たない
          （詳細なWARC情報・HTML本文は一切表示しない）。表示名・文言は
          依頼者確認前の仮のもの — docs/13_common_crawl_mvp_design.md
          「11. 依頼者確認が必要な点」参照。 */}
      {commonCrawlProvider && (
        <div className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
          <p>{commonCrawlProvider.summary}</p>
          {commonCrawlProvider.detail && <p>{commonCrawlProvider.detail}</p>}
          {/* URLのみを表示する（HTML/WARC本文・raw responseは
              meta.commonCrawlProvider自体にそのためのフィールドが
              存在しないため表示しようがない）。ラベル「取得ページ」は
              依頼者確認前の仮のもの — docs/15_requester_review_items.md
              参照。 */}
          {commonCrawlAnalyzedPages && (
            <div className="mt-1">
              <p>{commonCrawlAnalyzedPages.label}:</p>
              <ul className="list-inside list-disc">
                {commonCrawlAnalyzedPages.urls.map((url) => (
                  <li key={url} className="truncate">
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
                    >
                      {url}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {unavailableMessage ? (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-950 dark:text-amber-400">
          {unavailableMessage}
        </p>
      ) : items.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          共起語は見つかりませんでした。
        </p>
      ) : (
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
      )}
    </Card>
  );
}
