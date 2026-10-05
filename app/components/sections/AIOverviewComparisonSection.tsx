import Card from "../Card";
import {
  GEMINI_RERUN_BUTTON_LABEL,
  GEMINI_RERUN_HELPER_TEXT,
  GEMINI_RERUN_PENDING_TEXT,
} from "../../lib/analysis-history";
import {
  AI_OBSERVATION_COMMON_EXPLANATION_TEXT,
  AI_OVERVIEW_EXPLANATION_TEXT,
  CHATGPT_PLATFORM_NOTE,
  CLAUDE_PLATFORM_NOTE,
  GEMINI_GOOGLE_PLATFORM_LABEL,
  GEMINI_PLATFORM_NOTE,
  OWN_DOMAIN_STATUS_LABELS,
  getAiOverviewItemDetailDisplay,
  getAiOverviewProviderStatusDisplay,
  getChatGptProviderStatusDisplay,
  getClaudeProviderStatusDisplay,
  getGeminiProviderStatusDisplay,
  isGeminiRerunEligible,
} from "../../lib/meta-label";
import type { AiOverviewProviderStatusDisplay } from "../../lib/meta-label";
import type { AIOverviewComparisonItem, AnalysisMeta } from "../../lib/types";

// Passed down from the history detail page only (app/history/[id]/page.tsx)
// — the analysis result screen and the report page never pass this prop,
// so neither shows the rerun controls (レポート画面には再実行ボタンは
// 不要、分析直後の画面でも同様). `onRerun` is expected to show its own
// window.confirm() before doing anything (see GEMINI_RERUN_CONFIRM_MESSAGE
// in app/lib/analysis-history.ts) — this component only renders the
// button/description/in-flight-state, it never confirms on its own.
export type GeminiRerunControlsState = {
  status: "idle" | "pending";
  errorMessage?: string;
  successMessage?: string;
  onRerun: () => void;
};

function ProviderStatusBadge({ status }: { status: AiOverviewProviderStatusDisplay }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <span
        className={`rounded px-1.5 py-0.5 text-xs ${
          status.tone === "caution"
            ? "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400"
            : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
        }`}
      >
        {status.label}
      </span>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{status.description}</p>
      {status.caution && (
        <p className="text-xs text-amber-700 dark:text-amber-400">{status.caution}</p>
      )}
      {status.note && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{status.note}</p>
      )}
    </div>
  );
}

export default function AIOverviewComparisonSection({
  items,
  meta,
  geminiRerun,
}: {
  items: AIOverviewComparisonItem[];
  meta: AnalysisMeta;
  geminiRerun?: GeminiRerunControlsState;
}) {
  const providerStatus = getAiOverviewProviderStatusDisplay(meta);
  const chatgptStatus = getChatGptProviderStatusDisplay(meta);
  const claudeStatus = getClaudeProviderStatusDisplay(meta);
  const geminiStatus = getGeminiProviderStatusDisplay(meta);

  // isGeminiRerunEligible() is true only while there's something to
  // fix (a Gemini card flagged isTruncated === true) — a依頼者 reported
  // the button staying visible even after a successful rerun resolved
  // the truncation, so a normally-completed card must never show it.
  const showGeminiRerun = geminiRerun !== undefined && isGeminiRerunEligible(items);

  return (
    <Card
      title="4. AI Overview比較"
      description="AI Overview / ChatGPT / Claude / Gemini観測で確認された回答・参照状況（結果側の観測データ）"
    >
      <div className="mb-3 space-y-1 text-xs text-zinc-500 dark:text-zinc-400">
        <p>{AI_OVERVIEW_EXPLANATION_TEXT}</p>
        <p>{AI_OBSERVATION_COMMON_EXPLANATION_TEXT}</p>
        <p>{CHATGPT_PLATFORM_NOTE}</p>
        <p>{CLAUDE_PLATFORM_NOTE}</p>
        <p>{GEMINI_PLATFORM_NOTE}</p>
      </div>

      {(providerStatus || chatgptStatus || claudeStatus || geminiStatus) && (
        <div className="mb-3 flex flex-col gap-3">
          {providerStatus && <ProviderStatusBadge status={providerStatus} />}
          {chatgptStatus && <ProviderStatusBadge status={chatgptStatus} />}
          {claudeStatus && <ProviderStatusBadge status={claudeStatus} />}
          {geminiStatus && <ProviderStatusBadge status={geminiStatus} />}
        </div>
      )}

      {/* 1-column card layout (not a table) so long summaries/references
          wrap instead of forcing horizontal scroll — see docs/05_tasks.md. */}
      <div className="space-y-4">
        {items.map((item) => (
          <AIOverviewItemCard
            key={item.platform}
            item={item}
            geminiRerun={
              showGeminiRerun && item.platform === GEMINI_GOOGLE_PLATFORM_LABEL
                ? geminiRerun
                : undefined
            }
          />
        ))}
      </div>
    </Card>
  );
}

// "Geminiだけ再実行" — only ever rendered when the history detail page
// passes `geminiRerun` AND the Gemini card itself is flagged
// isTruncated === true (see isGeminiRerunEligible() above and
// GeminiRerunControlsState's doc comment). Attached directly to the
// Gemini card (see AIOverviewItemCard) — never shown elsewhere, and
// never shown for a normally-completed Gemini card.
function GeminiRerunControls({ controls }: { controls: GeminiRerunControlsState }) {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs dark:border-amber-900 dark:bg-amber-950">
      <p className="text-zinc-600 dark:text-zinc-400">{GEMINI_RERUN_HELPER_TEXT}</p>
      <button
        type="button"
        onClick={controls.onRerun}
        disabled={controls.status === "pending"}
        className="mt-2 rounded bg-zinc-800 px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
      >
        {controls.status === "pending" ? GEMINI_RERUN_PENDING_TEXT : GEMINI_RERUN_BUTTON_LABEL}
      </button>
      {controls.errorMessage && (
        <p className="mt-2 text-red-600 dark:text-red-400">{controls.errorMessage}</p>
      )}
      {controls.successMessage && (
        <p className="mt-2 text-emerald-600 dark:text-emerald-400">{controls.successMessage}</p>
      )}
    </div>
  );
}

function AIOverviewItemCard({
  item,
  geminiRerun,
}: {
  item: AIOverviewComparisonItem;
  geminiRerun?: GeminiRerunControlsState;
}) {
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
          {detail.platformNote && (
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              {detail.platformNote}
            </p>
          )}
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
          {detail.displaySummary}
        </p>
      </div>

      {detail.hasContinuation && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-zinc-500 dark:text-zinc-400">
            続きを見る
          </summary>
          <p className="mt-1 max-w-full whitespace-pre-wrap break-words leading-relaxed text-xs text-zinc-600 dark:text-zinc-400">
            {detail.continuationText}
          </p>
        </details>
      )}

      {detail.truncationWarning && (
        <p className="mt-3 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-700 dark:bg-amber-950 dark:text-amber-400">
          {detail.truncationWarning}
        </p>
      )}

      {geminiRerun && (
        <div className="mt-3">
          <GeminiRerunControls controls={geminiRerun} />
        </div>
      )}

      {detail.referenceSummary && (
        <div className="mt-3 min-w-0">
          <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
            参照元の内訳
          </h4>

          <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div className="rounded-md border border-zinc-200 px-2 py-1.5 text-center dark:border-zinc-800">
              <div className="text-[10px] text-zinc-500 dark:text-zinc-400">合計</div>
              <div className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                {detail.referenceSummary.total}件
              </div>
            </div>
            <div className="rounded-md border border-zinc-200 px-2 py-1.5 text-center dark:border-zinc-800">
              <div className="text-[10px] text-zinc-500 dark:text-zinc-400">自社公式</div>
              <div className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                {detail.referenceSummary.official}件
              </div>
            </div>
            <div className="rounded-md border border-zinc-200 px-2 py-1.5 text-center dark:border-zinc-800">
              <div className="text-[10px] text-zinc-500 dark:text-zinc-400">第三者</div>
              <div className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                {detail.referenceSummary.thirdParty}件
              </div>
            </div>
          </div>

          {detail.referenceSummary.categoryCounts.length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400">分類</p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {detail.referenceSummary.categoryCounts.map(({ label, count }) => (
                  <span
                    key={label}
                    className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
                  >
                    {label} {count}
                  </span>
                ))}
              </div>
            </div>
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
        <p
          className={`mt-3 rounded-md px-2 py-1.5 text-xs ${
            detail.ownDomainStatus === "included"
              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
              : "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400"
          }`}
        >
          {OWN_DOMAIN_STATUS_LABELS[detail.ownDomainStatus]}
        </p>
      )}
    </article>
  );
}
