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
                  <AIOverviewItemDetail item={item} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// Only ever has extra content for the DataForSEO provider (mock items
// never set fullSummary/references/ownDomainReferenced) — for every
// other item this renders identically to the old summary-only cell.
function AIOverviewItemDetail({ item }: { item: AIOverviewComparisonItem }) {
  const detail = getAiOverviewItemDetailDisplay(item);

  return (
    <div>
      <p>{item.summary}</p>

      {detail.hasDetail && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-zinc-500 dark:text-zinc-400">
            詳細を見る
          </summary>
          <p className="mt-1 whitespace-pre-wrap text-xs text-zinc-600 dark:text-zinc-400">
            {detail.detailText}
          </p>
        </details>
      )}

      {detail.references.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400">参照元</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-zinc-600 dark:text-zinc-400">
            {detail.references.map((reference, index) => (
              <li key={`${reference.url ?? reference.label}-${index}`}>
                {reference.url ? (
                  <a
                    href={reference.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    {reference.label}
                  </a>
                ) : (
                  reference.label
                )}
                {reference.title && ` — ${reference.title}`}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.ownDomainStatus !== "unjudged" && (
        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
          {OWN_DOMAIN_STATUS_LABELS[detail.ownDomainStatus]}
        </p>
      )}
    </div>
  );
}
