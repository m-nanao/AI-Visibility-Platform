import Card from "../Card";
import {
  OWN_DOMAIN_STATUS_LABELS,
  getAiOverviewItemDetailDisplay,
  getAiOverviewProviderStatusDisplay,
} from "../../lib/meta-label";
import type { AIOverviewComparisonItem, AnalysisMeta } from "../../lib/types";

export default function AIOverviewComparisonSection({
  items,
  meta,
}: {
  items: AIOverviewComparisonItem[];
  meta: AnalysisMeta;
}) {
  const providerStatus = getAiOverviewProviderStatusDisplay(meta);

  return (
    <Card
      title="4. AI Overview比較"
      description="主要AIサービスにおける掲載・言及状況の比較"
    >
      {providerStatus && (
        <div className="mb-3 flex flex-col items-start gap-1">
          <span
            className={`rounded px-1.5 py-0.5 text-xs ${
              providerStatus.tone === "caution"
                ? "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400"
                : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
            }`}
          >
            {providerStatus.label}
          </span>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {providerStatus.description}
          </p>
          {providerStatus.caution && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {providerStatus.caution}
            </p>
          )}
        </div>
      )}

      {/* 1-column card layout (not a table) so long summaries/references
          wrap instead of forcing horizontal scroll — see docs/05_tasks.md. */}
      <div className="space-y-4">
        {items.map((item) => (
          <AIOverviewItemCard key={item.platform} item={item} />
        ))}
      </div>
    </Card>
  );
}

function AIOverviewItemCard({ item }: { item: AIOverviewComparisonItem }) {
  const detail = getAiOverviewItemDetailDisplay(item);

  return (
    <article className="min-w-0 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="break-words font-medium text-zinc-800 dark:text-zinc-200">
            {item.platform}
          </h3>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            順位: {item.rank ? `${item.rank}位` : "—"}
          </p>
        </div>

        {item.mentioned ? (
          <span className="shrink-0 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400">
            掲載: あり
          </span>
        ) : (
          <span className="shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            掲載: なし
          </span>
        )}
      </div>

      <div className="mt-3">
        <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
          概要
        </h4>
        <p className="mt-1 max-w-full break-words leading-relaxed text-sm text-zinc-600 dark:text-zinc-400">
          {item.summary}
        </p>
      </div>

      {detail.hasDetail && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-zinc-500 dark:text-zinc-400">
            詳細を見る
          </summary>
          <p className="mt-1 max-w-full whitespace-pre-wrap break-words leading-relaxed text-xs text-zinc-600 dark:text-zinc-400">
            {detail.detailText}
          </p>
        </details>
      )}

      {detail.referenceSummary && (
        <div className="mt-3 min-w-0">
          <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
            参照元の内訳
          </h4>
          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
            参照元: {detail.referenceSummary.total}件（自社 {detail.referenceSummary.official} / 第三者{" "}
            {detail.referenceSummary.thirdParty}）
          </p>
          {detail.referenceSummary.presentCategoryLabels.length > 0 && (
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-500">
              分類: {detail.referenceSummary.presentCategoryLabels.join(", ")}
            </p>
          )}
        </div>
      )}

      {detail.references.length > 0 && (
        <div className="mt-3 min-w-0">
          <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
            参照元
          </h4>
          <ol className="mt-1.5 space-y-2 text-xs text-zinc-600 dark:text-zinc-400">
            {detail.references.map((reference, index) => (
              <li
                key={`${reference.url ?? reference.label}-${index}`}
                className="min-w-0"
              >
                <div className="flex min-w-0 gap-1.5">
                  <span className="shrink-0 text-zinc-400 dark:text-zinc-500">
                    {index + 1}.
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {reference.url ? (
                        <a
                          href={reference.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="max-w-full break-words underline"
                        >
                          {reference.label}
                        </a>
                      ) : (
                        <span className="max-w-full break-words">
                          {reference.label}
                        </span>
                      )}
                      {reference.categoryLabel && (
                        <span className="shrink-0 rounded bg-zinc-100 px-1 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                          {reference.categoryLabel}
                        </span>
                      )}
                    </div>
                    {reference.title && reference.title !== reference.label && (
                      <p className="max-w-full break-words text-zinc-500 dark:text-zinc-500">
                        {reference.title}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {detail.ownDomainStatus !== "unjudged" && (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
          {OWN_DOMAIN_STATUS_LABELS[detail.ownDomainStatus]}
        </p>
      )}
    </article>
  );
}
