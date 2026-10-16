"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import AppHeader from "../../../components/AppHeader";
import AnalysisDashboard from "../../../components/AnalysisDashboard";
import RetryAnalysisControls from "../../../components/RetryAnalysisControls";
import { buildHistoryDetailPath } from "../../../lib/analysis-history";
import { parseAnalysisRunDetailResponse } from "../../../lib/analysis-history-schema";
import {
  JOB_CANCEL_BUTTON_LABEL,
  JOB_CANCEL_CONFIRM_MESSAGE,
  JOB_CANCEL_PENDING_TEXT,
  JOB_FAILED_LEASE_EXPIRED_EXPLANATION,
  JOB_FAILED_UNEXPECTED_EXPLANATION,
  JOB_FAILED_VALIDATION_LABEL,
  JOB_STATUS_BACK_TO_INPUT_TEXT,
  JOB_STATUS_COMPLETED_HEADING,
  JOB_STATUS_FAILED_BODY,
  JOB_STATUS_FAILED_HEADING,
  JOB_STATUS_LONG_WAIT_MESSAGE,
  JOB_STATUS_PARTIAL_BODY,
  JOB_STATUS_PARTIAL_HEADING,
  JOB_STATUS_QUEUED_BODY,
  JOB_STATUS_QUEUED_HEADING,
  JOB_STATUS_RESULT_LINK_TEXT,
  JOB_STATUS_RUNNING_BODY,
  JOB_STATUS_RUNNING_HEADING,
  JOB_STATUS_WORKER_CAVEAT,
  LONG_WAIT_THRESHOLD_MS,
  RETRY_CONFIRM_MESSAGE,
  buildAnalysisJobPath,
  classifyJobFailure,
  isAsyncAnalysisEnabled,
  isTerminalJobStatus,
  parseRetryableAnalysisInput,
  resolveAnalysisJobResultOutcome,
  resolveAnalysisJobStatusOutcome,
  resolveCancelAnalysisJobOutcome,
  submitRetryAnalysis,
} from "../../../lib/analysis-jobs";
import type {
  AnalysisJobResultViewState,
  AnalysisJobStatusViewState,
  RetryAnalysisInputPreview,
} from "../../../lib/analysis-jobs";
import { createAnalysisJobPollController } from "../../../lib/analysis-job-poll-controller";

/**
 * The async-job analysis status/result screen —
 * docs/40_async_analysis_jobs_design.md "15. Phase 3". Reached from
 * app/page.tsx (when NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS=true) right
 * after POST /api/analysis-jobs returns 202, and also directly via
 * its own URL (reload, bookmark, a link from history) — the
 * `analysisRunId` in the URL is the only state this page depends on;
 * everything else is re-fetched from the backend on every load (see
 * the polling effect below), never assumed to still be true from a
 * previous visit.
 *
 * All display logic (status text, which outcomes stop polling, how
 * to interpret a fetch Response) lives in app/lib/analysis-jobs.ts /
 * app/lib/analysis-job-polling.ts as plain, unit-tested functions —
 * this component is deliberately thin wiring around them (same
 * convention as app/history/[id]/page.tsx).
 */
export default function AnalysisJobPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id;
  const [view, setView] = useState<AnalysisJobStatusViewState>({ kind: "loading" });
  const [resultView, setResultView] = useState<AnalysisJobResultViewState>({ kind: "loading" });
  const [showLongWait, setShowLongWait] = useState(false);
  // Keeps the latest status reachable from the long-wait timer's
  // callback without re-registering that timer on every poll tick.
  const latestStatusRef = useRef<string | undefined>(undefined);
  // Cancel (queued-only) — independent of the polling effect above, so
  // an in-flight cancel request is never confused with a poll tick.
  const [isCancelling, setIsCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  // Manual retry (failed-only) — this job's own status endpoint
  // doesn't expose input_snapshot/projectId (AnalysisJobStatusResponse
  // never has, see backend/models.py), so once the job reaches
  // "failed" this fetches the one existing endpoint that does —
  // GET /api/analysis-runs/{id} — purely for that data, never to
  // re-derive the failed/queued/running view state itself (the
  // ongoing poll above already owns that).
  const [retryProjectId, setRetryProjectId] = useState<string | undefined>(undefined);
  const [retryPreview, setRetryPreview] = useState<RetryAnalysisInputPreview | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  // Keeps the raw inputSnapshot reachable from handleRetry() without
  // putting the whole (potentially large) object in component state —
  // only the derived, display-ready `retryPreview` needs to trigger a
  // re-render.
  const retryInputSnapshotRef = useRef<Record<string, unknown> | undefined>(undefined);

  const handleRetry = async () => {
    if (!retryProjectId || !retryInputSnapshotRef.current || isRetrying) return;
    if (!window.confirm(RETRY_CONFIRM_MESSAGE)) return;

    setIsRetrying(true);
    setRetryError(null);

    const outcome = await submitRetryAnalysis(retryInputSnapshotRef.current, retryProjectId);

    if (outcome.kind === "accepted") {
      router.push(buildAnalysisJobPath(outcome.analysisRunId));
      return;
    }

    setRetryError(outcome.message);
    setIsRetrying(false);
  };

  // Confirms, calls DELETE /api/analysis-jobs/{id}, and handles the
  // three outcomes the task calls for: success -> back to the history
  // list; 409 ("no longer queued" — a worker may have just claimed it)
  // -> re-fetch the real current status via the exact same resolver
  // the poll controller itself uses, rather than show a stale "queued"
  // view or a misleading error; anything else -> an inline error,
  // leaving the queued view (and the button) as they were. `isCancelling`
  // both disables the button and guards the handler itself against a
  // second click firing a second request while the first is in flight.
  const handleCancel = async () => {
    if (!id || isCancelling) return;
    if (!window.confirm(JOB_CANCEL_CONFIRM_MESSAGE)) return;

    setIsCancelling(true);
    setCancelError(null);

    const response = await fetch(`/api/analysis-jobs/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }).catch(() => null);
    const outcome = await resolveCancelAnalysisJobOutcome(response);

    if (outcome.kind === "cancelled") {
      router.push("/history");
      return;
    }

    if (outcome.kind === "conflict") {
      const statusResponse = await fetch(`/api/analysis-jobs/${encodeURIComponent(id)}`).catch(
        () => null,
      );
      const statusOutcome = await resolveAnalysisJobStatusOutcome(statusResponse);
      setView(statusOutcome);
      if (statusOutcome.kind === "status") {
        latestStatusRef.current = statusOutcome.job.status;
      }
      setIsCancelling(false);
      return;
    }

    setCancelError(outcome.message);
    setIsCancelling(false);
  };

  // Status polling: delegated to createAnalysisJobPollController()
  // (app/lib/analysis-job-poll-controller.ts), which owns every
  // concurrency decision — never more than one status fetch in
  // flight, a `visibilitychange` while a fetch is already running
  // never starts a second one, a stale response can never overwrite a
  // newer one, no state update after unmount, and polling stops for
  // good after a terminal status (completed/partial/failed) or a
  // 401/403/404 — see that module's docstring for the full list. This
  // component only wires the controller's dependencies to the real
  // fetch/document/window and forwards the outcome into `view`.
  useEffect(() => {
    if (!id) return;

    const controller = createAnalysisJobPollController({
      fetchStatus: (signal) =>
        fetch(`/api/analysis-jobs/${encodeURIComponent(id)}`, { signal }).catch(() => null),
      onOutcome: (outcome) => {
        setView(outcome);
        if (outcome.kind === "status") {
          latestStatusRef.current = outcome.job.status;
        }
      },
      isVisible: () => document.visibilityState === "visible",
      setTimeout: (callback, delayMs) => setTimeout(callback, delayMs),
      clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    });

    function handleVisibilityChange() {
      controller.handleVisibilityChange(document.visibilityState === "visible");
    }

    controller.start();
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      controller.stop();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [id]);

  // Fetches the saved result exactly once, only after the job has
  // actually reached "completed"/"partial" — never polled, and never
  // attempted for "queued"/"running"/"failed" (a failed job has no
  // result to fetch; its errorMessage already comes from the status
  // response above).
  useEffect(() => {
    if (!id) return;
    if (view.kind !== "status") return;
    if (view.job.status !== "completed" && view.job.status !== "partial") return;

    let cancelled = false;

    async function loadResult() {
      const response = await fetch(
        `/api/analysis-jobs/${encodeURIComponent(id)}/result`,
      ).catch(() => null);
      if (cancelled) return;
      const outcome = await resolveAnalysisJobResultOutcome(response);
      if (cancelled) return;
      setResultView(outcome);
    }

    loadResult();
    return () => {
      cancelled = true;
    };
    // Re-runs only when the job transitions into a status that
    // warrants fetching the result — not on every poll tick, since
    // `view` changing from "running" to "running" again (same status,
    // different object identity) would otherwise re-fetch needlessly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, view.kind === "status" ? view.job.status : undefined]);

  // Fetches input_snapshot/projectId exactly once, only after the job
  // reaches "failed" — needed only to offer the manual-retry preview
  // (see handleRetry above); never attempted for
  // "queued"/"running"/"completed"/"partial". Reuses the existing
  // GET /api/analysis-runs/{id} proxy (the job's own status endpoint
  // doesn't expose this) and the same envelope parser the history
  // detail page uses, but intentionally stops at the parsed envelope —
  // this page's own `view` (from the polling effect above) is already
  // the source of truth for "failed", so this never also tries to
  // resolve a result/jobFailed view state from it.
  useEffect(() => {
    if (!id) return;
    if (view.kind !== "status") return;
    if (view.job.status !== "failed") return;

    let cancelled = false;

    async function loadInputSnapshotForRetry() {
      const response = await fetch(`/api/analysis-runs/${encodeURIComponent(id)}`).catch(
        () => null,
      );
      if (cancelled || !response || !response.ok) return;
      const json = await response.json().catch(() => null);
      if (cancelled) return;
      const parsed = parseAnalysisRunDetailResponse(json);
      if (cancelled || !parsed.success) return;

      retryInputSnapshotRef.current = parsed.data.run.inputSnapshot;
      setRetryPreview(parseRetryableAnalysisInput(parsed.data.run.inputSnapshot));
      setRetryProjectId(parsed.data.projectId);
    }

    loadInputSnapshotForRetry();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, view.kind === "status" ? view.job.status : undefined]);

  // An honest "this is taking a while" notice — never a fabricated
  // progress percentage or ETA, since the backend provides neither
  // (docs/40 Phase 3 task's "5. 分析中画面"). Cleared automatically
  // once a terminal status is reached (the effect above stops
  // updating `view` at that point, so this timer firing afterward is
  // harmless, but suppressed anyway via the `stopped`-equivalent
  // check on latestStatusRef below for a cleaner UI).
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      const status = latestStatusRef.current;
      if (!status || !isTerminalJobStatus(status)) {
        setShowLongWait(true);
      }
    }, LONG_WAIT_THRESHOLD_MS);
    return () => clearTimeout(timeoutId);
  }, []);

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-6 py-8">
        {view.kind === "loading" && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            分析の状態を確認しています...
          </p>
        )}

        {(view.kind === "unauthorized" ||
          view.kind === "forbidden" ||
          view.kind === "notFound" ||
          view.kind === "error") && (
          <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            <p>{view.message}</p>
            <div className="mt-3">
              <Link
                href="/"
                className="text-sm text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
              >
                {JOB_STATUS_BACK_TO_INPUT_TEXT}
              </Link>
            </div>
          </div>
        )}

        {view.kind === "status" && (
          <JobStatusBody
            status={view.job.status}
            errorMessage={view.job.errorMessage}
            showLongWait={showLongWait}
            resultView={resultView}
            onCancel={handleCancel}
            isCancelling={isCancelling}
            cancelError={cancelError}
            retryPreview={retryProjectId ? retryPreview : null}
            onRetry={handleRetry}
            isRetrying={isRetrying}
            retryError={retryError}
          />
        )}
      </main>
    </div>
  );
}

function JobStatusBody({
  status,
  errorMessage,
  showLongWait,
  resultView,
  onCancel,
  isCancelling,
  cancelError,
  retryPreview,
  onRetry,
  isRetrying,
  retryError,
}: {
  status: string;
  errorMessage?: string;
  showLongWait: boolean;
  resultView: AnalysisJobResultViewState;
  onCancel: () => void;
  isCancelling: boolean;
  cancelError: string | null;
  retryPreview: RetryAnalysisInputPreview | null;
  onRetry: () => void;
  isRetrying: boolean;
  retryError: string | null;
}) {
  if (status === "queued" || status === "running") {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
          {status === "queued" ? JOB_STATUS_QUEUED_HEADING : JOB_STATUS_RUNNING_HEADING}
        </h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
          {status === "queued" ? JOB_STATUS_QUEUED_BODY : JOB_STATUS_RUNNING_BODY}
        </p>
        {showLongWait && (
          <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            {JOB_STATUS_LONG_WAIT_MESSAGE}
          </p>
        )}
        <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-500">
          {JOB_STATUS_WORKER_CAVEAT}
        </p>
        {/* キャンセルはqueuedの間だけ提示する — runningは既にworkerが
            claimしており即時停止できないため、ボタン自体を出さない
            (runningジョブを即時停止できると誤認させないため)。本当の
            権限チェック（作成者本人のみ）はbackend側が必ず行う——ここ
            でのボタン表示/非表示はUXのためだけで、権限判定の代わりでは
            ない。 */}
        {status === "queued" && (
          <div className="mt-4">
            <button
              type="button"
              onClick={onCancel}
              disabled={isCancelling}
              className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950"
            >
              {isCancelling ? JOB_CANCEL_PENDING_TEXT : JOB_CANCEL_BUTTON_LABEL}
            </button>
            {cancelError && (
              <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">{cancelError}</p>
            )}
          </div>
        )}
      </div>
    );
  }

  if (status === "failed") {
    // 分析が正常完了していないことをheading/bodyで明示したうえで、
    // errorMessageの内容（backendが書き込む3種類の固定・安全な文言の
    // いずれか——classifyJobFailure()のコメント参照）に応じて追加の
    // 説明を出し分ける。生の例外・スタックトレース・APIキー等は
    // backend側でそもそもerror_messageに書かれないため、ここで追加の
    // マスキングは不要。
    const failureCategory = classifyJobFailure(errorMessage);
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
          {JOB_STATUS_FAILED_HEADING}
        </h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">{JOB_STATUS_FAILED_BODY}</p>
        {failureCategory === "leaseExpired" && (
          <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            {JOB_FAILED_LEASE_EXPIRED_EXPLANATION}
          </p>
        )}
        {failureCategory === "unexpected" && (
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            {JOB_FAILED_UNEXPECTED_EXPLANATION}
          </p>
        )}
        {failureCategory === "validation" && errorMessage && (
          <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
            {JOB_FAILED_VALIDATION_LABEL} {errorMessage}
          </p>
        )}
        <RetryAnalysisControls
          preview={retryPreview}
          isAsyncEnabled={isAsyncAnalysisEnabled()}
          isRetrying={isRetrying}
          retryError={retryError}
          onRetry={onRetry}
        />
        <div className="mt-4">
          <Link
            href="/"
            className="inline-flex h-9 items-center justify-center rounded-md bg-zinc-900 px-4 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {JOB_STATUS_BACK_TO_INPUT_TEXT}
          </Link>
        </div>
      </div>
    );
  }

  // completed / partial
  return (
    <div>
      <div className="mb-4 rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
          {status === "partial" ? JOB_STATUS_PARTIAL_HEADING : JOB_STATUS_COMPLETED_HEADING}
        </h1>
        {status === "partial" && (
          <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
            {JOB_STATUS_PARTIAL_BODY}
          </p>
        )}
      </div>

      {resultView.kind === "loading" && (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">結果を読み込んでいます...</p>
      )}

      {(resultView.kind === "unauthorized" ||
        resultView.kind === "forbidden" ||
        resultView.kind === "notFound" ||
        resultView.kind === "incompatible" ||
        resultView.kind === "error") && (
        <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
          <p>{resultView.message}</p>
        </div>
      )}

      {resultView.kind === "notReady" && (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">結果を読み込んでいます...</p>
      )}

      {resultView.kind === "failed" && (
        <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
          <p>{JOB_STATUS_FAILED_BODY}</p>
          {resultView.errorMessage && (
            <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
              {resultView.errorMessage}
            </p>
          )}
        </div>
      )}

      {resultView.kind === "success" && (
        <>
          {resultView.result.analysisRunId && (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950">
              <p className="text-sm text-blue-900 dark:text-blue-200">
                保存済みの履歴詳細からもこの結果を確認できます。
              </p>
              <Link
                href={buildHistoryDetailPath(resultView.result.analysisRunId)}
                className="shrink-0 rounded bg-blue-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-800 dark:bg-blue-600 dark:hover:bg-blue-500"
              >
                {JOB_STATUS_RESULT_LINK_TEXT}
              </Link>
            </div>
          )}
          <AnalysisDashboard result={resultView.result} />
        </>
      )}
    </div>
  );
}
