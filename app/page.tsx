"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppHeader from "./components/AppHeader";
import BrandInputForm from "./components/BrandInputForm";
import AnalysisDashboard from "./components/AnalysisDashboard";
import {
  ANALYZE_FALLBACK_HEADER,
  ANALYZE_FALLBACK_REASON_HEADER,
  buildAnalyzeRequestBody,
  clearPendingSyncAnalysisRequest,
  getAnalyzeFallbackMessage,
  isAnalyzeAuthRequiredEnabled,
  isTerminalAnalyzeConflictCode,
  resolveRequestIdForSyncAnalysis,
  type AnalyzeQuotaInfo,
} from "./lib/analysis-request";
import {
  resolveAnalyzeErrorDisplay,
  resolveAnalyzeQuotaDisplay,
  type AnalyzeErrorDisplay,
} from "./lib/analyze-error-display";
import {
  ANALYSIS_RESULT_PREVIEW_NOTE,
  HISTORY_LIST_LINK_TEXT,
  HISTORY_LIST_PATH,
  POST_ANALYZE_HISTORY_CARD_HEADING,
  POST_ANALYZE_HISTORY_LINK_HELPER_TEXT,
  POST_ANALYZE_HISTORY_LINK_TEXT,
  resolvePostAnalyzeHistoryLink,
} from "./lib/analysis-history";
import {
  CREATE_JOB_GENERIC_ERROR_MESSAGE,
  ME_PROJECTS_NONE_MESSAGE,
  UNKNOWN_USER_SCOPE,
  buildAnalysisJobPath,
  clearPendingJobSubmission,
  isAsyncAnalysisEnabled,
  isDefinitiveCreateAnalysisJobOutcome,
  prepareAnalysisJobCreateRequestBody,
  resolveCreateAnalysisJobOutcome,
  resolveMeProjectsOutcome,
} from "./lib/analysis-jobs";
import type { MeProjectsOutcome } from "./lib/analysis-jobs";
import { getSectionStatusSummary } from "./lib/meta-label";
import { STAGING_BANNER_TEXT } from "./lib/staging-banner";
import { useSupabaseSession } from "./lib/supabase/useSupabaseSession";
import type {
  AiOverviewProviderMode,
  AnalysisResult,
  ChatGptProviderMode,
  ClaudeProviderMode,
  CommonCrawlProviderMode,
  GeminiProviderMode,
} from "./lib/types";

type Status = "idle" | "loading" | "done" | "error";

export default function Home() {
  const router = useRouter();
  // Build-time constant (NEXT_PUBLIC_*) — not state, since it never
  // changes within a running app. False (unset, the production
  // default) means every branch below involving project
  // resolution/job creation is simply never reached — the component
  // behaves exactly as it did before this flag existed.
  const asyncAnalysisEnabled = isAsyncAnalysisEnabled();
  // Task 6-B2 (feature/sync-analyze-jwt-project-auth) — a separate
  // flag from asyncAnalysisEnabled above (see
  // isAnalyzeAuthRequiredEnabled()'s doc for why), false by default so
  // this page behaves exactly as before this task for as long as it
  // stays false (the production default as of this task).
  const analyzeAuthRequired = isAnalyzeAuthRequiredEnabled();
  // Only consulted for its email (used to scope the idempotency key
  // below so one signed-in user's pending-submission record is never
  // reused by a different signed-in user sharing the same browser tab
  // — see app/lib/analysis-jobs.ts's resolveIdempotencyKeyForJobSubmission()).
  // This page has no auth *gate* of its own (unlike /history/*, see
  // AuthGuard) — a signed-out visitor still sees this hook resolve to
  // "signed-out" and simply falls back to UNKNOWN_USER_SCOPE; the
  // actual authentication requirement is enforced by the backend via
  // GET /api/me/projects / POST /api/analysis-jobs regardless.
  const sessionState = useSupabaseSession();
  const userScope = sessionState.status === "signed-in" ? sessionState.email ?? UNKNOWN_USER_SCOPE : UNKNOWN_USER_SCOPE;

  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  // Plain-string error, used only by the async-job flow
  // (handleAsyncAnalyze, Task 6-B2 Phase 3 — out of this task's
  // scope) — left exactly as it was before Task 6-B5.
  const [error, setError] = useState<string | null>(null);
  // Structured error, used only by the synchronous flow
  // (handleAnalyze, Task 6-B2/6-B3/6-B4) — Task 6-B5 adds this so the
  // render below can show a login link / project-reselect affordance
  // alongside the message, derived from the exact HTTP status + stable
  // `code` the backend sent (see app/lib/analyze-error-display.ts).
  const [errorDisplay, setErrorDisplay] = useState<AnalyzeErrorDisplay | null>(null);
  // Whether the in-flight (or most recently finished) request included
  // urls, so the loading message can say "fetching web pages" instead
  // of the generic message — url-based analysis can take much longer.
  const [isUrlAnalysis, setIsUrlAnalysis] = useState(false);
  // Set from ANALYZE_FALLBACK_HEADER/ANALYZE_FALLBACK_REASON_HEADER
  // (app/lib/analysis-request.ts) when /api/analyze had to fall back to
  // dummy data — see that file's comment for why this can legitimately
  // happen even though the Python API ends up completing and saving a
  // real result (full-ON requests taking longer than this route is
  // willing to wait). null on a real result.
  const [fallbackMessage, setFallbackMessage] = useState<string | null>(null);

  // Project resolution — originally added for the async-job flow only
  // (docs/40 Phase 3 task "1"/"4", POST /analysis-jobs requires an
  // explicit `projectId`), and reused as-is by Task 6-B2
  // (feature/sync-analyze-jwt-project-auth) for the sync flow's own
  // projectId requirement once analyzeAuthRequired is true — same
  // shape, same GET /api/me/projects call, same auto-select-when-one
  // behavior. Entirely unused, and never fetched, when both flags are
  // false.
  const [projectsOutcome, setProjectsOutcome] = useState<MeProjectsOutcome>({ kind: "loading" });
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  // Extracted from the effect below so Task 6-B5's 403 (project
  // access denied) error display can offer a "プロジェクト一覧を再取得"
  // affordance that reuses this exact same fetch — never a fabricated
  // "check status" action, just genuinely re-running the one real
  // project-list lookup this app already has.
  const reloadProjects = useCallback(async () => {
    const response = await fetch("/api/me/projects").catch(() => null);
    const outcome = await resolveMeProjectsOutcome(response);
    setProjectsOutcome(outcome);
    if (outcome.kind === "success" && outcome.projectIds.length === 1) {
      setSelectedProjectId(outcome.projectIds[0]);
    }
    return outcome;
  }, []);

  useEffect(() => {
    if (!asyncAnalysisEnabled && !analyzeAuthRequired) return;
    let cancelled = false;

    async function loadProjects() {
      const response = await fetch("/api/me/projects").catch(() => null);
      if (cancelled) return;
      const outcome = await resolveMeProjectsOutcome(response);
      if (cancelled) return;
      setProjectsOutcome(outcome);
      if (outcome.kind === "success" && outcome.projectIds.length === 1) {
        setSelectedProjectId(outcome.projectIds[0]);
      }
    }

    loadProjects();
    return () => {
      cancelled = true;
    };
  }, [asyncAnalysisEnabled, analyzeAuthRequired]);

  const handleAsyncAnalyze = async (
    brandName: string,
    urls: string[],
    aiOverviewMode?: AiOverviewProviderMode,
    chatgptMode?: ChatGptProviderMode,
    commonCrawlMode?: CommonCrawlProviderMode,
    commonCrawlDomain?: string,
    claudeMode?: ClaudeProviderMode,
    geminiMode?: GeminiProviderMode,
  ) => {
    if (!selectedProjectId) {
      setError(ME_PROJECTS_NONE_MESSAGE);
      setStatus("error");
      return;
    }

    setStatus("loading");
    setError(null);
    setFallbackMessage(null);

    const body = prepareAnalysisJobCreateRequestBody(
      userScope,
      selectedProjectId,
      brandName,
      urls,
      aiOverviewMode,
      chatgptMode,
      commonCrawlMode,
      commonCrawlDomain,
      claudeMode,
      geminiMode,
    );

    const response = await fetch("/api/analysis-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);

    const outcome = await resolveCreateAnalysisJobOutcome(response);
    if (isDefinitiveCreateAnalysisJobOutcome(outcome)) {
      // A definitive conclusion (accepted, or the input/request was
      // rejected outright) — the next explicit "分析開始" click must
      // get a fresh idempotency key, never this one. A network-level
      // failure ("error") deliberately skips this, so retrying with
      // the same input reuses the same key (docs/40 "10.1").
      clearPendingJobSubmission();
    }

    if (outcome.kind === "accepted") {
      router.push(buildAnalysisJobPath(outcome.analysisRunId));
      return;
    }

    setError(outcome.kind === "error" ? CREATE_JOB_GENERIC_ERROR_MESSAGE : outcome.message);
    setStatus("error");
  };

  const handleAnalyze = async (
    brandName: string,
    urls: string[],
    aiOverviewMode?: AiOverviewProviderMode,
    chatgptMode?: ChatGptProviderMode,
    commonCrawlMode?: CommonCrawlProviderMode,
    commonCrawlDomain?: string,
    claudeMode?: ClaudeProviderMode,
    geminiMode?: GeminiProviderMode,
  ) => {
    if (asyncAnalysisEnabled) {
      await handleAsyncAnalyze(
        brandName,
        urls,
        aiOverviewMode,
        chatgptMode,
        commonCrawlMode,
        commonCrawlDomain,
        claudeMode,
        geminiMode,
      );
      return;
    }

    // Task 6-B2 (feature/sync-analyze-jwt-project-auth): mirrors
    // handleAsyncAnalyze's own early-return guard above — the submit
    // button is already disabled in this state (see isLoading's
    // wiring below), so this is defense in depth, never the only
    // thing standing between an unauthenticated/project-less caller
    // and a submission. Entirely skipped when analyzeAuthRequired is
    // false (today's production default), so this can never fire in
    // production as of this task.
    if (analyzeAuthRequired) {
      if (sessionState.status !== "signed-in") {
        setErrorDisplay(
          resolveAnalyzeErrorDisplay(401, null, "authentication required"),
        );
        setStatus("error");
        return;
      }
      if (!selectedProjectId) {
        setErrorDisplay(
          resolveAnalyzeErrorDisplay(400, "project_id_required", "projectId is required"),
        );
        setStatus("error");
        return;
      }
    }

    setStatus("loading");
    setErrorDisplay(null);
    setFallbackMessage(null);
    setIsUrlAnalysis(urls.length > 0);
    try {
      // urls: [] is never sent — omitting the key entirely lets the
      // API fall back to its own default (development sample
      // documents), and keeps `urls: []` reserved as an explicit
      // "reject this request" signal on the API side. aiOverviewMode/
      // chatgptMode/commonCrawlMode/commonCrawlDomain/claudeMode/
      // geminiMode are only present when BrandInputForm's
      // dev/verification-only mode selectors are shown (see
      // app/lib/analysis-request.ts) — otherwise they're undefined and
      // omitted here too, same as before. projectId is only present
      // when analyzeAuthRequired is true (Task 6-B2) — otherwise
      // omitted exactly as before this field existed.
      const requestBody = buildAnalyzeRequestBody(
        brandName,
        urls,
        aiOverviewMode,
        chatgptMode,
        commonCrawlMode,
        commonCrawlDomain,
        claudeMode,
        geminiMode,
        analyzeAuthRequired ? selectedProjectId ?? undefined : undefined,
      );

      // Task 6-B3 (feature/sync-analyze-jwt-project-auth): requestId is
      // only ever generated/sent when analyzeAuthRequired is true —
      // the backend's DB-level idempotency enforcement is scoped to
      // the authenticated path only (see
      // app/lib/analysis-request.ts's AnalyzeRequestBody doc), so the
      // anonymous flow stays byte-for-byte unchanged. Resolved from
      // `requestBody` *before* requestId is added to it, same as
      // app/lib/analysis-jobs.ts's own idempotency-key pattern —
      // reused across a retry of the exact same input, fresh for a
      // genuinely new submission.
      if (analyzeAuthRequired) {
        requestBody.requestId = resolveRequestIdForSyncAnalysis(
          userScope,
          selectedProjectId ?? "",
          requestBody,
        );
      }

      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null);
        const code = errorBody && typeof errorBody.code === "string" ? errorBody.code : null;
        const serverMessage =
          errorBody && typeof errorBody.error === "string"
            ? errorBody.error
            : "分析に失敗しました。";

        if (response.status === 429) {
          // Task 6-B4/6-B5: usage-quota exceeded — no analysis_runs
          // row was ever created for this attempt (see backend/main.py's
          // AnalysisQuotaExceededError handling), so there is nothing
          // for a later retry with the SAME requestId to conflict
          // with; the requestId is kept (not cleared) so a retry of
          // the same input is recognized as the same logical attempt,
          // mirroring the still-running 409 case below.
          const quota =
            errorBody && errorBody.quota && typeof errorBody.quota === "object"
              ? (errorBody.quota as AnalyzeQuotaInfo)
              : null;
          setErrorDisplay(resolveAnalyzeQuotaDisplay(quota, serverMessage));
          setStatus("error");
          return;
        }

        if (response.status === 409) {
          // "still running" is not a definitive outcome — keep the
          // same requestId so a later resubmission (once the analysis
          // actually finishes) can still reuse it. Every other 409
          // cause (previously failed / input conflict / cancelled), and
          // every other non-409 rejection below, is definitive: the
          // next explicit "分析開始" click must get a fresh requestId.
          if (isTerminalAnalyzeConflictCode(code)) {
            clearPendingSyncAnalysisRequest();
          }
          setErrorDisplay(resolveAnalyzeErrorDisplay(409, code, serverMessage));
          setStatus("error");
          return;
        }

        clearPendingSyncAnalysisRequest();
        setErrorDisplay(resolveAnalyzeErrorDisplay(response.status, code, serverMessage));
        setStatus("error");
        return;
      }

      // Task 6-B3 audit fix (不具合A): a 200 response here does NOT
      // necessarily mean the real analysis actually finished — when
      // the Python API didn't answer in time (or at all), this is the
      // dummy-fallback response (see app/api/analyze/route.ts's
      // PYTHON_API_TIMEOUT_MS comment: "the Python API keeps running
      // ... and may still save a real result"). Its true server-side
      // outcome (still running / already completed / already failed)
      // is unknown to this client, so the pending requestId must be
      // kept — never cleared — so a resubmission of the same input
      // naturally reuses it and lets the backend's own idempotency
      // judgment (replay / 409 still-running / 409 previously-failed)
      // decide, instead of this client blindly starting a second,
      // independent (and potentially paid) execution under a fresh
      // key. Only a confirmed real result (no fallback header) clears
      // it. Found by the Task 6-B3 audit's real-PostgreSQL
      // verification: without this guard, a fallback response clears
      // the key just like a real success would, defeating the whole
      // idempotency mechanism in exactly its most common trigger
      // (a slow full-ON request exceeding this route's own timeout).
      const isDummyFallback = Boolean(response.headers.get(ANALYZE_FALLBACK_HEADER));
      if (isDummyFallback) {
        setFallbackMessage(
          getAnalyzeFallbackMessage(response.headers.get(ANALYZE_FALLBACK_REASON_HEADER)),
        );
      } else {
        clearPendingSyncAnalysisRequest();
      }

      const data: AnalysisResult = await response.json();
      setResult(data);
      setStatus("done");
    } catch (err) {
      // Network-level failure (fetch() itself rejected) — never a
      // response status, so resolveAnalyzeErrorDisplay() doesn't
      // apply; the pending requestId is deliberately NOT cleared here
      // (same "unknown true outcome" reasoning as the dummy-fallback
      // case above), so a retry of the same input reuses it.
      setErrorDisplay({
        kind: "generic",
        title: "分析中にエラーが発生しました",
        message:
          err instanceof Error ? err.message : "分析中にエラーが発生しました。",
        showLoginLink: false,
        showProjectReselect: false,
      });
      setStatus("error");
    }
  };


  const handleReset = () => {
    setStatus("idle");
    setResult(null);
    setError(null);
    setErrorDisplay(null);
    setFallbackMessage(null);
    setIsUrlAnalysis(false);
  };

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <AppHeader />
      <div className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Web上の情報環境をもとに、ブランドがAI上でどのように扱われやすいかを推定します
          </p>
          <p className="mt-2 inline-block rounded bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            {STAGING_BANNER_TEXT}
          </p>
        </div>
      </div>

      <main className="mx-auto max-w-5xl px-6 py-8">
        {(asyncAnalysisEnabled || analyzeAuthRequired) && (
          <AsyncProjectNotice
            outcome={projectsOutcome}
            selectedProjectId={selectedProjectId}
            onSelectProjectId={(projectId) => {
              // A different project means a different requestId scope
              // (app/lib/analysis-request.ts's resolveRequestIdForSyncAnalysis()
              // already hashes on projectId, so this alone guarantees
              // the old requestId is never reused for the new
              // selection) — clearing the stale error display here is
              // purely a UX nicety, not required for correctness.
              setSelectedProjectId(projectId);
              setErrorDisplay(null);
            }}
          />
        )}

        <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <BrandInputForm
            onSubmit={handleAnalyze}
            isLoading={
              status === "loading" ||
              ((asyncAnalysisEnabled || analyzeAuthRequired) && !selectedProjectId)
            }
            initialValue={result?.brandName ?? ""}
          />
        </div>

        {error && (
          <p className="mt-4 text-sm text-rose-600 dark:text-rose-400">
            {error}
          </p>
        )}

        {errorDisplay && (
          <div className="mt-4 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-400">
            <p className="font-medium">{errorDisplay.title}</p>
            <p className="mt-0.5">{errorDisplay.message}</p>
            {(errorDisplay.showLoginLink || errorDisplay.showProjectReselect) && (
              <div className="mt-2 flex flex-wrap gap-3">
                {errorDisplay.showLoginLink && (
                  <Link
                    href="/login"
                    className="text-xs font-medium underline-offset-2 hover:underline"
                  >
                    ログインする
                  </Link>
                )}
                {errorDisplay.showProjectReselect && (
                  <button
                    type="button"
                    onClick={() => {
                      reloadProjects();
                    }}
                    className="text-xs font-medium underline-offset-2 hover:underline"
                  >
                    プロジェクト一覧を再取得
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {status === "loading" && (
          <p className="mt-8 text-sm text-zinc-500 dark:text-zinc-400">
            {isUrlAnalysis
              ? "Webページを取得・分析しています。20〜25秒ほどかかる場合があります..."
              : "分析中です。しばらくお待ちください..."}
          </p>
        )}

        {status === "done" && result && (
          <div className="mt-8">
            {/* Prominent callout — only when the result was actually
                saved (result.analysisRunId set). Placed above
                everything else in the result area, per
                improve/history-centered-analysis-flow's "分析結果の
                上部、できれば目立つカード形式" — the analysis result
                screen is a preview; the history detail screen is
                where the saved result/report/Gemini rerun actually
                live. */}
            {(() => {
              const historyLink = resolvePostAnalyzeHistoryLink(result.analysisRunId);
              if (!historyLink) return null;
              return (
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950">
                  <div>
                    <p className="text-sm font-medium text-blue-900 dark:text-blue-200">
                      {POST_ANALYZE_HISTORY_CARD_HEADING}
                    </p>
                    <p className="mt-0.5 text-xs text-blue-800 dark:text-blue-300">
                      {POST_ANALYZE_HISTORY_LINK_HELPER_TEXT}
                    </p>
                  </div>
                  <Link
                    href={historyLink.path}
                    className="shrink-0 rounded bg-blue-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-800 dark:bg-blue-600 dark:hover:bg-blue-500"
                  >
                    {POST_ANALYZE_HISTORY_LINK_TEXT}
                  </Link>
                </div>
              );
            })()}

            {/* Task 6-B5: when this is a genuinely real result (not a
                dummy fallback — fallbackMessage covers that case
                separately below) but analysisRunId is null, the
                history card above correctly renders nothing — but a
                silent absence could easily be mistaken for "it just
                hasn't finished saving yet." Scoped to the
                authenticated path only: in Task 6-B3's lease-expiry
                case specifically, the real result shown here is known
                to not be retrievable later (see
                backend/main.py's _analyze_authenticated_idempotent(),
                which sets analysisRunId=None exactly when
                complete_analysis_job() lost that race) — the
                anonymous path's own (unrelated, pre-existing) reasons
                for a null analysisRunId are left with their existing,
                unchanged behavior (no note), since this task must not
                alter that regression-tested flow. */}
            {analyzeAuthRequired && !result.analysisRunId && !fallbackMessage && (
              <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                この分析結果は履歴に保存されていません。あとで見返したい場合は、今のうちに内容を保存してください。
              </p>
            )}

            {/* Always shown while a result is displayed, kept
                deliberately short/muted so it doesn't compete with the
                result content itself on a normal run. */}
            <p className="mb-3 text-xs text-zinc-400 dark:text-zinc-500">
              {ANALYSIS_RESULT_PREVIEW_NOTE}
            </p>

            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h2 className="text-sm text-zinc-500 dark:text-zinc-400">
                  「{result.brandName}」の分析結果
                </h2>
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                  {getSectionStatusSummary(result.meta)}
                </span>
              </div>
              <button
                type="button"
                onClick={handleReset}
                className="text-sm text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
              >
                リセット
              </button>
            </div>
            {fallbackMessage && (
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                <div>
                  <p>{fallbackMessage}</p>
                  {/* Task 6-B5: only accurate once analyzeAuthRequired
                      is true — the anonymous flow has no idempotency
                      mechanism at all, so clicking "分析開始" again
                      there genuinely starts a brand-new, independent
                      analysis rather than safely checking/replaying
                      this one. This app has no dedicated status-check
                      API, so this explicitly describes the existing
                      submit button's own behavior, never implying a
                      separate "確認する" action exists. */}
                  {analyzeAuthRequired && (
                    <p className="mt-1 text-xs">
                      同じ内容でもう一度「分析開始」を押すと、処理中かどうかを安全に確認できます（二重に分析が実行されることはありません）。
                    </p>
                  )}
                </div>
                <Link
                  href={HISTORY_LIST_PATH}
                  className="shrink-0 text-xs font-medium underline-offset-2 hover:underline"
                >
                  {HISTORY_LIST_LINK_TEXT}
                </Link>
              </div>
            )}
            <AnalysisDashboard result={result} />
          </div>
        )}
      </main>
    </div>
  );
}

/**
 * Shown only in the async-job flow (NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS
 * =true) — docs/40 Phase 3 task "1. 実装前の確認" found no existing
 * frontend concept of "project" at all, so this is new UI needed
 * purely to resolve the `projectId` POST /analysis-jobs requires:
 * auto-selects when the user has exactly one accessible project,
 * offers a plain `<select>` when they have more than one, and shows a
 * clear "cannot start" message when they have none — never silently
 * guesses or leaves the submit button enabled with no project chosen
 * (see app/page.tsx's `isLoading` wiring above).
 */
function AsyncProjectNotice({
  outcome,
  selectedProjectId,
  onSelectProjectId,
}: {
  outcome: MeProjectsOutcome;
  selectedProjectId: string | null;
  onSelectProjectId: (projectId: string) => void;
}) {
  if (outcome.kind === "loading") {
    return (
      <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
        利用可能なプロジェクトを確認しています...
      </p>
    );
  }

  if (outcome.kind === "unauthorized" || outcome.kind === "error") {
    return (
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-400">
        <p>{outcome.message}</p>
        {/* ログイン導線（Task 6-B2「JWT認証エラー時はログイン導線を示す」）
            — unauthorizedのみ（errorはDB/サーバー障害等、ログインでは解決
            しない別の問題のため導線を出さない）。 */}
        {outcome.kind === "unauthorized" && (
          <Link
            href="/login"
            className="shrink-0 text-xs font-medium underline-offset-2 hover:underline"
          >
            ログインする
          </Link>
        )}
      </div>
    );
  }

  // success
  if (outcome.projectIds.length === 0) {
    return (
      <p className="mb-4 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-400">
        {ME_PROJECTS_NONE_MESSAGE}
      </p>
    );
  }

  if (outcome.projectIds.length === 1) {
    // Auto-selected already (see the useEffect above) — nothing to
    // show here.
    return null;
  }

  return (
    <div className="mb-4">
      <label
        htmlFor="asyncAnalysisProjectId"
        className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300"
      >
        分析対象プロジェクト
      </label>
      <select
        id="asyncAnalysisProjectId"
        value={selectedProjectId ?? ""}
        onChange={(event) => onSelectProjectId(event.target.value)}
        className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50 sm:w-auto"
      >
        <option value="" disabled>
          選択してください
        </option>
        {outcome.projectIds.map((projectId) => (
          <option key={projectId} value={projectId}>
            {projectId}
          </option>
        ))}
      </select>
    </div>
  );
}
