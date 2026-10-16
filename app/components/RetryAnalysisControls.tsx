"use client";

// Shared "re-run this analysis with the same input" UI — rendered
// identically by the failed-job progress page
// (app/analysis/jobs/[id]/page.tsx) and the completed/partial history
// detail page (app/history/[id]/page.tsx), per
// feature/async-job-failure-display-and-retry's "再分析の共通ロジック
// を作成". The actual submission logic lives in
// app/lib/analysis-jobs.ts's submitRetryAnalysis() — this component is
// purely the preview + confirm + pending/error display around it, so
// both pages share one implementation of "what does the user see
// before/during/after clicking retry" instead of two copies drifting
// apart.
import {
  RETRY_BUTTON_LABEL,
  RETRY_DISABLED_BY_FLAG_MESSAGE,
  RETRY_NOT_RETRYABLE_MESSAGE,
  RETRY_PENDING_TEXT,
  retryMayCallPaidProvider,
} from "../lib/analysis-jobs";
import type { RetryAnalysisInputPreview } from "../lib/analysis-jobs";

const PROVIDER_FIELDS: Array<{
  key: keyof Pick<
    RetryAnalysisInputPreview,
    "aiOverviewMode" | "chatgptMode" | "claudeMode" | "geminiMode" | "commonCrawlMode"
  >;
  label: string;
}> = [
  { key: "aiOverviewMode", label: "AI Overview" },
  { key: "chatgptMode", label: "ChatGPT" },
  { key: "claudeMode", label: "Claude" },
  { key: "geminiMode", label: "Gemini" },
  { key: "commonCrawlMode", label: "Common Crawl" },
];

export default function RetryAnalysisControls({
  preview,
  isAsyncEnabled,
  isRetrying,
  retryError,
  onRetry,
}: {
  preview: RetryAnalysisInputPreview | null;
  isAsyncEnabled: boolean;
  isRetrying: boolean;
  retryError: string | null;
  onRetry: () => void;
}) {
  // feature flagはUX制御であり、backend認可の代替ではない——
  // NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS=falseの間はこのボタン自体を
  // 出さないことで「新しいジョブを作れない」ことを分かりやすくするが、
  // 実際の作成可否は常にbackendのANALYSIS_JOBS_ENABLED/project権限
  // 判定が決める。
  if (!isAsyncEnabled) {
    return (
      <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-500">
        {RETRY_DISABLED_BY_FLAG_MESSAGE}
      </p>
    );
  }

  if (!preview) {
    return (
      <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-500">
        {RETRY_NOT_RETRYABLE_MESSAGE}
      </p>
    );
  }

  const providerEntries = PROVIDER_FIELDS.filter(({ key }) => preview[key]);

  return (
    <div className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-800/50">
      <p className="text-xs text-zinc-600 dark:text-zinc-300">
        次の内容で新しい分析を開始します: <span className="font-medium">{preview.brandName}</span>
        （{preview.inputKind === "documents" ? "文章" : "URL"} {preview.inputCount}件）
      </p>
      {providerEntries.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
          {providerEntries.map(({ key, label }) => (
            <li key={key}>
              {label}: {preview[key]}
            </li>
          ))}
        </ul>
      )}
      <p
        className={
          retryMayCallPaidProvider(preview)
            ? "mt-1 text-[11px] font-medium text-amber-700 dark:text-amber-400"
            : "mt-1 text-[11px] text-zinc-500 dark:text-zinc-400"
        }
      >
        設定によっては外部の有料APIが再度呼び出される場合があります。
      </p>
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        className="mt-2 rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:text-zinc-300 dark:hover:bg-zinc-700"
      >
        {isRetrying ? RETRY_PENDING_TEXT : RETRY_BUTTON_LABEL}
      </button>
      {retryError && <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">{retryError}</p>}
    </div>
  );
}
