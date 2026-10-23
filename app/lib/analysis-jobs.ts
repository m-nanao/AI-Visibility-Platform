// Types, display text, idempotency-key management, and view-state
// resolution for Phase 3 of docs/40_async_analysis_jobs_design.md
// (the async-job analysis UI). Mirrors app/lib/analysis-history.ts's
// own conventions — display strings/logic as plain exported
// constants/functions, not inline JSX, so they stay unit-testable
// without a React component-rendering library (this project doesn't
// have one).
//
// Gated end-to-end by NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS (see
// isAsyncAnalysisEnabled() below) — independent of the backend's own
// ANALYSIS_JOBS_ENABLED/ANALYSIS_JOBS_WORKER_ENABLED flags. With this
// unset (the production default), nothing in this file is ever
// reached from app/page.tsx — the existing synchronous POST /analyze
// flow is completely unaffected.

import { buildAnalyzeRequestBody, type AnalyzeRequestBody } from "./analysis-request";
import {
  parseAnalysisJobAcceptedResponse,
  parseAnalysisJobResultResponse,
  parseAnalysisJobStatusResponse,
  parseMeProjectsResponse,
} from "./analysis-jobs-schema";
import { parseAnalysisResult } from "./analysis-result-schema";
import type {
  AiOverviewProviderMode,
  AnalysisResult,
  ChatGptProviderMode,
  ClaudeProviderMode,
  CommonCrawlProviderMode,
  GeminiProviderMode,
} from "./types";

/**
 * Whether the async-job analysis flow is enabled at all. False (the
 * production default when this env var is unset) means app/page.tsx
 * must behave exactly as it always has — the synchronous POST
 * /analyze flow, completely unaffected by anything in this file.
 */
export function isAsyncAnalysisEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS === "true";
}

// --- GET /api/me/projects ---------------------------------------------------

export type MeProjectsOutcome =
  | { kind: "loading" }
  | { kind: "unauthorized"; message: string }
  | { kind: "error"; message: string }
  | { kind: "success"; projectIds: string[] };

export const ME_PROJECTS_UNAUTHORIZED_MESSAGE =
  "分析を開始するにはログインが必要です。";
export const ME_PROJECTS_ERROR_MESSAGE =
  "利用可能なプロジェクトを確認できませんでした。時間をおいて再度お試しください。";
export const ME_PROJECTS_NONE_MESSAGE =
  "分析を開始できるプロジェクトがありません。管理者にお問い合わせください。";

/**
 * Turns a fetch() Response (or null, on a network-level failure) from
 * /api/me/projects into an outcome app/page.tsx can act on directly —
 * mirrors app/lib/analysis-history.ts's resolve*FetchOutcome()
 * functions. 401/403 both map to "unauthorized" (the caller has no
 * session, or it's expired) since this is a JWT-only lookup with no
 * further access-control nuance to distinguish.
 */
export async function resolveMeProjectsOutcome(
  response: Response | null,
): Promise<MeProjectsOutcome> {
  if (!response) {
    return { kind: "error", message: ME_PROJECTS_ERROR_MESSAGE };
  }

  if (response.status === 401 || response.status === 403) {
    return { kind: "unauthorized", message: ME_PROJECTS_UNAUTHORIZED_MESSAGE };
  }

  if (!response.ok) {
    return { kind: "error", message: ME_PROJECTS_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  const parsed = parseMeProjectsResponse(json);
  if (!parsed.success) {
    return { kind: "error", message: ME_PROJECTS_ERROR_MESSAGE };
  }

  return { kind: "success", projectIds: parsed.data.projects.map((project) => project.id) };
}

// --- idempotency key management ---------------------------------------------
//
// One idempotency key per "start analysis" operation (docs/40
// "10.1"). Persisted in sessionStorage (not localStorage — this is a
// single-tab, single-session concern, and sessionStorage surviving a
// reload within the same tab is exactly the "reload before a response
// ever arrived" scenario this is meant to cover) keyed together with
// a hash of the exact input that key was generated for:
// - same input, no key yet -> generate and store a new one.
// - same input, a key already stored for it -> reuse it (a retry of
//   the same operation, including after a reload, reuses the same
//   key rather than creating a second job — docs/40 "10.1"/"10.2").
// - different input -> the hash won't match, so a fresh key is
//   generated — editing the form before resubmitting, or starting a
//   genuinely new analysis, is always a new operation with a new key.

const PENDING_JOB_SUBMISSION_STORAGE_KEY = "async-analysis-pending-job-submission";

type PendingJobSubmissionRecord = { idempotencyKey: string; inputHash: string };

function hashJobSubmissionInput(
  userScope: string,
  projectId: string,
  content: AnalyzeRequestBody,
): string {
  // `content` is always built by buildAnalyzeRequestBody() with a
  // fixed key order, so JSON.stringify is a stable, deterministic
  // serialization here — no need for a real hash function for this
  // comparison-only purpose. `userScope` (see
  // resolveIdempotencyKeyForJobSubmission()'s docstring) is included
  // so a stored key is never reused across two different signed-in
  // users sharing the same browser tab, even if their projectId/
  // content happen to be identical.
  return JSON.stringify({ userScope, projectId, content });
}

function readPendingJobSubmission(): PendingJobSubmissionRecord | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(PENDING_JOB_SUBMISSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as PendingJobSubmissionRecord).idempotencyKey === "string" &&
      typeof (parsed as PendingJobSubmissionRecord).inputHash === "string"
    ) {
      return parsed as PendingJobSubmissionRecord;
    }
    return null;
  } catch {
    // sessionStorage unavailable (private browsing, quota, etc.) —
    // treat as "no pending submission" rather than throwing.
    return null;
  }
}

function writePendingJobSubmission(record: PendingJobSubmissionRecord): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      PENDING_JOB_SUBMISSION_STORAGE_KEY,
      JSON.stringify(record),
    );
  } catch {
    // Not fatal — the key generated this call is still returned and
    // used for this request; it just won't be recoverable after a
    // reload if storage itself is unavailable.
  }
}

/** Generates a fresh, random idempotency key. Separated from
 * resolveIdempotencyKeyForJobSubmission() below so a test can inject
 * a deterministic generator instead of depending on
 * `crypto.randomUUID()`. */
export function generateIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback for an environment without crypto.randomUUID (very old
  // browsers) — not cryptographically strong, but uniqueness (not
  // unpredictability) is all this value needs.
  return `fallback-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Resolves the idempotency key to use for a "start analysis"
 * submission with the given `userScope`/`projectId`/`content` —
 * reusing a previously stored key if (and only if) it was generated
 * for the exact same input, otherwise generating and persisting a new
 * one. See the module-level comment above for the full reasoning.
 *
 * `userScope` identifies *who* is submitting (the signed-in user's
 * email — see app/page.tsx's call site, which reads it from
 * useSupabaseSession()) — included specifically so a stored key from
 * one signed-in user is never reused for a different signed-in user
 * who happens to submit identical projectId/content in the same
 * browser tab (e.g. a shared machine where one person logs out and
 * another logs in without closing the tab). A caller with no
 * resolvable identity (not signed in, or Supabase unconfigured) must
 * still pass *some* stable string — app/page.tsx uses a fixed
 * sentinel in that case — never an empty string, which would
 * otherwise collide with a different caller's equally-empty scope.
 */
export function resolveIdempotencyKeyForJobSubmission(
  userScope: string,
  projectId: string,
  content: AnalyzeRequestBody,
  generateKey: () => string = generateIdempotencyKey,
): string {
  const inputHash = hashJobSubmissionInput(userScope, projectId, content);
  const existing = readPendingJobSubmission();
  if (existing && existing.inputHash === inputHash) {
    return existing.idempotencyKey;
  }

  const idempotencyKey = generateKey();
  writePendingJobSubmission({ idempotencyKey, inputHash });
  return idempotencyKey;
}

/**
 * Clears the stored pending-submission record — called once a
 * submission reaches a definitive outcome (a job was accepted, or the
 * input itself was rejected) so the *next* explicit "start analysis"
 * click always gets a brand-new key, never an old one left over from
 * an unrelated earlier attempt. Deliberately NOT called on a
 * network-level failure or an ambiguous server error — those are
 * exactly the cases a retry should reuse the same key for.
 */
export function clearPendingJobSubmission(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(PENDING_JOB_SUBMISSION_STORAGE_KEY);
  } catch {
    // ignore
  }
}

// --- POST /api/analysis-jobs -------------------------------------------------

export interface AnalysisJobCreateRequestBody extends AnalyzeRequestBody {
  projectId: string;
  idempotencyKey: string;
}

/** Builds the POST /api/analysis-jobs request body — reuses
 * buildAnalyzeRequestBody() verbatim for the analysis-input fields
 * (brandName/urls/aiOverviewMode/chatgptMode/commonCrawlMode/
 * commonCrawlDomain/claudeMode/geminiMode), since POST /analysis-jobs
 * accepts exactly the same shape POST /analyze always has, plus the
 * two fields unique to a job (see backend/models.py's
 * AnalysisJobCreateRequest). */
export function buildAnalysisJobCreateRequestBody(
  projectId: string,
  idempotencyKey: string,
  brandName: string,
  urls: string[],
  aiOverviewMode?: AiOverviewProviderMode,
  chatgptMode?: ChatGptProviderMode,
  commonCrawlMode?: CommonCrawlProviderMode,
  commonCrawlDomain?: string,
  claudeMode?: ClaudeProviderMode,
  geminiMode?: GeminiProviderMode,
  officialUrl?: string,
): AnalysisJobCreateRequestBody {
  const content = buildAnalyzeRequestBody(
    brandName,
    urls,
    aiOverviewMode,
    chatgptMode,
    commonCrawlMode,
    commonCrawlDomain,
    claudeMode,
    geminiMode,
    undefined, // projectId — not part of AnalyzeRequestBody's own projectId slot here.
    undefined, // requestId — jobs use idempotencyKey below, not requestId.
    officialUrl,
  );
  return { ...content, projectId, idempotencyKey };
}

/** Fallback scope passed to resolveIdempotencyKeyForJobSubmission()
 * when no signed-in user identity is resolvable (should not normally
 * be reached — POST /api/analysis-jobs requires a session — but kept
 * explicit rather than passing an empty string, which could otherwise
 * collide with another equally-unresolved caller). */
export const UNKNOWN_USER_SCOPE = "unknown-user";

/**
 * Convenience wrapper for the real submission call site
 * (app/page.tsx): builds the analysis-input content, resolves the
 * idempotency key for it (reusing a stored one for a retry of the
 * exact same input by the exact same user, see
 * resolveIdempotencyKeyForJobSubmission() above), and returns the
 * full POST /api/analysis-jobs body in one call. Kept separate from
 * buildAnalysisJobCreateRequestBody() above (which takes an explicit
 * `idempotencyKey`) so that function stays trivially testable with an
 * injected key, while this one owns the actual key-resolution side
 * effect (reading/writing sessionStorage).
 */
export function prepareAnalysisJobCreateRequestBody(
  userScope: string,
  projectId: string,
  brandName: string,
  urls: string[],
  aiOverviewMode?: AiOverviewProviderMode,
  chatgptMode?: ChatGptProviderMode,
  commonCrawlMode?: CommonCrawlProviderMode,
  commonCrawlDomain?: string,
  claudeMode?: ClaudeProviderMode,
  geminiMode?: GeminiProviderMode,
  officialUrl?: string,
): AnalysisJobCreateRequestBody {
  const content = buildAnalyzeRequestBody(
    brandName,
    urls,
    aiOverviewMode,
    chatgptMode,
    commonCrawlMode,
    commonCrawlDomain,
    claudeMode,
    geminiMode,
    undefined, // projectId — not part of AnalyzeRequestBody's own projectId slot here.
    undefined, // requestId — jobs use idempotencyKey below, not requestId.
    officialUrl,
  );
  const idempotencyKey = resolveIdempotencyKeyForJobSubmission(userScope, projectId, content);
  return { ...content, projectId, idempotencyKey };
}

export type CreateAnalysisJobOutcome =
  | { kind: "accepted"; analysisRunId: string; status: string }
  | { kind: "unauthorized"; message: string }
  | { kind: "forbidden"; message: string }
  | { kind: "conflict"; message: string }
  | { kind: "rateLimited"; message: string }
  | { kind: "disabled"; message: string }
  | { kind: "invalidInput"; message: string }
  | { kind: "error"; message: string };

export const CREATE_JOB_UNAUTHORIZED_MESSAGE = "ログインが必要です。再度ログインしてください。";
export const CREATE_JOB_FORBIDDEN_MESSAGE = "このプロジェクトで分析を開始する権限がありません。";
export const CREATE_JOB_CONFLICT_MESSAGE =
  "直前の分析開始操作と内容が異なります。入力を確認して再度お試しください。";
export const CREATE_JOB_RATE_LIMITED_MESSAGE =
  "同時に実行できる分析の件数が上限に達しています。しばらくしてから再度お試しください。";
export const CREATE_JOB_DISABLED_MESSAGE = "非同期分析は現在利用できません。";
export const CREATE_JOB_GENERIC_ERROR_MESSAGE =
  "分析を開始できませんでした。時間をおいて再度お試しください。";

/**
 * Turns a fetch() Response (or null, on a network-level failure) from
 * /api/analysis-jobs into an outcome app/page.tsx can act on
 * directly. A definitive outcome (accepted / forbidden / conflict /
 * rateLimited / disabled / invalidInput) means the caller should
 * clearPendingJobSubmission() so the next explicit submission gets a
 * fresh idempotency key — "error" (network failure or an unexpected
 * status) deliberately does NOT get that treatment, so a retry of the
 * exact same input reuses the same key (docs/40 "10.1").
 */
export async function resolveCreateAnalysisJobOutcome(
  response: Response | null,
): Promise<CreateAnalysisJobOutcome> {
  if (!response) {
    return { kind: "error", message: CREATE_JOB_GENERIC_ERROR_MESSAGE };
  }

  if (response.status === 404) {
    // The job endpoints are entirely unregistered (404) when the
    // backend's ANALYSIS_JOBS_ENABLED is off — see
    // backend/main.py's _resolve_job_auth().
    return { kind: "disabled", message: CREATE_JOB_DISABLED_MESSAGE };
  }

  if (response.status === 401) {
    return { kind: "unauthorized", message: CREATE_JOB_UNAUTHORIZED_MESSAGE };
  }

  if (response.status === 403) {
    return { kind: "forbidden", message: CREATE_JOB_FORBIDDEN_MESSAGE };
  }

  if (response.status === 409) {
    return { kind: "conflict", message: CREATE_JOB_CONFLICT_MESSAGE };
  }

  if (response.status === 429) {
    return { kind: "rateLimited", message: CREATE_JOB_RATE_LIMITED_MESSAGE };
  }

  if (response.status === 400) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : CREATE_JOB_GENERIC_ERROR_MESSAGE;
    return { kind: "invalidInput", message };
  }

  if (!response.ok) {
    return { kind: "error", message: CREATE_JOB_GENERIC_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  const parsed = parseAnalysisJobAcceptedResponse(json);
  if (!parsed.success) {
    return { kind: "error", message: CREATE_JOB_GENERIC_ERROR_MESSAGE };
  }

  return { kind: "accepted", analysisRunId: parsed.data.analysisRunId, status: parsed.data.status };
}

/** True for every CreateAnalysisJobOutcome that represents a
 * definitive conclusion to this submission attempt (so the caller
 * should clear the pending idempotency-key record) — false only for
 * "error" (network failure / unexpected response), which should keep
 * the same key available for a retry. */
export function isDefinitiveCreateAnalysisJobOutcome(outcome: CreateAnalysisJobOutcome): boolean {
  return outcome.kind !== "error";
}

// --- job detail path ---------------------------------------------------------

/** Builds the /analysis/jobs/{id} path for a newly created job. */
export function buildAnalysisJobPath(analysisRunId: string): string {
  return `/analysis/jobs/${encodeURIComponent(analysisRunId)}`;
}

// --- GET /api/analysis-jobs/{id} ---------------------------------------------

export type AnalysisJobStatus = "queued" | "running" | "completed" | "partial" | "failed";

export type AnalysisJobStatusResponse = {
  analysisRunId: string;
  status: string;
  startedAt?: string;
  completedAt?: string;
  errorMessage?: string;
};

export type AnalysisJobStatusViewState =
  | { kind: "loading" }
  | { kind: "unauthorized"; message: string }
  | { kind: "forbidden"; message: string }
  | { kind: "notFound"; message: string }
  | { kind: "error"; message: string }
  | { kind: "status"; job: AnalysisJobStatusResponse };

export const JOB_STATUS_UNAUTHORIZED_MESSAGE =
  "ログインが必要です。再度ログインしてから、このページを開き直してください。";
export const JOB_STATUS_FORBIDDEN_MESSAGE = "この分析ジョブを表示する権限がありません。";
export const JOB_STATUS_NOT_FOUND_MESSAGE =
  "指定された分析ジョブが見つかりません。削除された可能性があります。";
export const JOB_STATUS_GENERIC_ERROR_MESSAGE =
  "分析の状態を確認できませんでした。時間をおいて再度お試しください。";

/** Turns a fetch() Response (or null) from /api/analysis-jobs/{id}
 * into a view state the job status page can render directly —
 * mirrors app/lib/analysis-history.ts's resolveHistoryDetailFetchOutcome(). */
export async function resolveAnalysisJobStatusOutcome(
  response: Response | null,
): Promise<AnalysisJobStatusViewState> {
  if (!response) {
    return { kind: "error", message: JOB_STATUS_GENERIC_ERROR_MESSAGE };
  }

  if (response.status === 401) {
    return { kind: "unauthorized", message: JOB_STATUS_UNAUTHORIZED_MESSAGE };
  }

  if (response.status === 403) {
    return { kind: "forbidden", message: JOB_STATUS_FORBIDDEN_MESSAGE };
  }

  if (response.status === 404) {
    return { kind: "notFound", message: JOB_STATUS_NOT_FOUND_MESSAGE };
  }

  if (!response.ok) {
    return { kind: "error", message: JOB_STATUS_GENERIC_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  const parsed = parseAnalysisJobStatusResponse(json);
  if (!parsed.success) {
    return { kind: "error", message: JOB_STATUS_GENERIC_ERROR_MESSAGE };
  }

  return {
    kind: "status",
    job: {
      analysisRunId: parsed.data.analysisRunId,
      status: parsed.data.status,
      startedAt: parsed.data.startedAt,
      completedAt: parsed.data.completedAt,
      errorMessage: parsed.data.errorMessage,
    },
  };
}

/** Terminal job statuses — once reached, polling stops and the status
 * never changes again (docs/40 "9"/"11.4": a failed job is never
 * automatically requeued). */
const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set(["completed", "partial", "failed"]);

export function isTerminalJobStatus(status: string): boolean {
  return TERMINAL_JOB_STATUSES.has(status);
}

// --- status display text -----------------------------------------------------

export const JOB_STATUS_QUEUED_HEADING = "分析受付済み";
export const JOB_STATUS_QUEUED_BODY = "処理開始までお待ちください。";
export const JOB_STATUS_RUNNING_HEADING = "分析中";
export const JOB_STATUS_RUNNING_BODY =
  "Web上の情報とAI各社の観測結果を確認しています。しばらく時間がかかる場合があります。";
export const JOB_STATUS_COMPLETED_HEADING = "分析完了";
export const JOB_STATUS_PARTIAL_HEADING = "一部の結果が利用可能です";
export const JOB_STATUS_PARTIAL_BODY =
  "一部の項目は取得できませんでした。利用可能な結果を表示します。";
export const JOB_STATUS_FAILED_HEADING = "分析に失敗しました";
export const JOB_STATUS_FAILED_BODY =
  "分析を完了できませんでした。入力内容を確認して、もう一度お試しください。";
export const JOB_STATUS_RESULT_LINK_TEXT = "結果を見る";
export const JOB_STATUS_BACK_TO_INPUT_TEXT = "分析入力に戻る";
export const JOB_STATUS_WORKER_CAVEAT =
  "このページを閉じても、処理が稼働中であれば分析は継続されます。Renderの無料プランではサーバーが一時停止することがあり、その場合は処理の開始が遅れることがあります。";
export const JOB_STATUS_LONG_WAIT_MESSAGE =
  "通常より時間がかかっています。このままお待ちいただくか、後でこのページに戻って確認することもできます。";

/** Minimum elapsed time (ms) since the job was accepted before
 * showing JOB_STATUS_LONG_WAIT_MESSAGE — an honest "this is taking a
 * while" notice, never a fabricated progress percentage or ETA (the
 * backend provides neither). */
export const LONG_WAIT_THRESHOLD_MS = 60_000;

export function getStatusHeading(status: string): string {
  switch (status) {
    case "queued":
      return JOB_STATUS_QUEUED_HEADING;
    case "running":
      return JOB_STATUS_RUNNING_HEADING;
    case "completed":
      return JOB_STATUS_COMPLETED_HEADING;
    case "partial":
      return JOB_STATUS_PARTIAL_HEADING;
    case "failed":
      return JOB_STATUS_FAILED_HEADING;
    default:
      return status;
  }
}

// --- GET /api/analysis-jobs/{id}/result --------------------------------------

export type AnalysisJobResultViewState =
  | { kind: "loading" }
  | { kind: "notReady" }
  | { kind: "unauthorized"; message: string }
  | { kind: "forbidden"; message: string }
  | { kind: "notFound"; message: string }
  | { kind: "incompatible"; message: string }
  | { kind: "failed"; errorMessage?: string }
  | { kind: "error"; message: string }
  | { kind: "success"; result: AnalysisResult; status: string };

export const JOB_RESULT_INCOMPATIBLE_MESSAGE =
  "保存済み分析結果の形式が現在の表示形式と一致しません。";
export const JOB_RESULT_GENERIC_ERROR_MESSAGE =
  "分析結果を読み込めませんでした。時間をおいて再度お試しください。";

/** Turns a fetch() Response (or null) from
 * /api/analysis-jobs/{id}/result into a view state — mirrors
 * resolveAnalysisJobStatusOutcome() above. 409 ("not finished yet",
 * see backend/main.py) is distinct from every other outcome so the
 * caller can show a "still processing" message rather than a generic
 * error. A "failed" job is a 200 with no `result` (see
 * backend/models.py's AnalysisJobResultResponse) — handled as its own
 * `kind` rather than folded into "error", since it's an expected,
 * well-formed outcome, not a transport/validation failure. */
export async function resolveAnalysisJobResultOutcome(
  response: Response | null,
): Promise<AnalysisJobResultViewState> {
  if (!response) {
    return { kind: "error", message: JOB_RESULT_GENERIC_ERROR_MESSAGE };
  }

  if (response.status === 401) {
    return { kind: "unauthorized", message: JOB_STATUS_UNAUTHORIZED_MESSAGE };
  }

  if (response.status === 403) {
    return { kind: "forbidden", message: JOB_STATUS_FORBIDDEN_MESSAGE };
  }

  if (response.status === 404) {
    return { kind: "notFound", message: JOB_STATUS_NOT_FOUND_MESSAGE };
  }

  if (response.status === 409) {
    return { kind: "notReady" };
  }

  if (!response.ok) {
    return { kind: "error", message: JOB_RESULT_GENERIC_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  const parsed = parseAnalysisJobResultResponse(json);
  if (!parsed.success) {
    return { kind: "error", message: JOB_RESULT_GENERIC_ERROR_MESSAGE };
  }

  if (parsed.data.status === "failed") {
    return { kind: "failed", errorMessage: parsed.data.errorMessage };
  }

  // A placeholder/empty result_json={} (see backend's "never surface
  // the placeholder as a real result" rule) fails parseAnalysisResult()
  // the same way any other malformed result would — this is covered
  // by the same "incompatible" outcome, never shown as a success.
  if (!parsed.data.result) {
    return { kind: "incompatible", message: JOB_RESULT_INCOMPATIBLE_MESSAGE };
  }

  const resultParsed = parseAnalysisResult(parsed.data.result);
  if (!resultParsed.success) {
    return { kind: "incompatible", message: JOB_RESULT_INCOMPATIBLE_MESSAGE };
  }

  return { kind: "success", result: resultParsed.data, status: parsed.data.status };
}

// --- DELETE /api/analysis-jobs/{id} (cancel a queued job) --------------------
//
// Mirrors backend/main.py's cancel_analysis_job() —
// docs/40_async_analysis_jobs_design.md "24". Only ever offered in the
// UI while a job's last-known status is "queued" (see
// app/analysis/jobs/[id]/page.tsx); the backend enforces the real
// rule (creator-only, queued-only) regardless of what the UI shows, so
// this resolver's job is purely to turn the proxy's response into a
// view-level outcome, the same shape as every other resolve*Outcome()
// in this file.

export type CancelAnalysisJobOutcome =
  | { kind: "cancelled" }
  | { kind: "unauthorized"; message: string }
  | { kind: "forbidden"; message: string }
  | { kind: "notFound"; message: string }
  // The job is no longer cancellable (already claimed by a worker, or
  // already in a terminal status) — the caller must re-fetch the
  // job's current status rather than show this as a plain error, see
  // the page's handleCancel().
  | { kind: "conflict"; message: string }
  | { kind: "error"; message: string };

export const JOB_CANCEL_BUTTON_LABEL = "分析をキャンセル";
export const JOB_CANCEL_CONFIRM_MESSAGE =
  "この分析をキャンセルしますか？キャンセルした分析は元に戻せません。";
export const JOB_CANCEL_PENDING_TEXT = "キャンセルしています...";
export const JOB_CANCEL_UNAUTHORIZED_MESSAGE =
  "ログインが必要です。再度ログインしてから、このページを開き直してください。";
export const JOB_CANCEL_FORBIDDEN_MESSAGE =
  "この分析をキャンセルする権限がありません。";
export const JOB_CANCEL_NOT_FOUND_MESSAGE =
  "指定された分析ジョブが見つかりません。削除された可能性があります。";
export const JOB_CANCEL_CONFLICT_MESSAGE =
  "処理が開始されたため、キャンセルできませんでした。最新の状態を表示します。";
export const JOB_CANCEL_GENERIC_ERROR_MESSAGE =
  "分析をキャンセルできませんでした。時間をおいて再度お試しください。";

/** Turns a fetch() Response (or null) from DELETE /api/analysis-jobs/{id}
 * into a view-level outcome — mirrors every other resolve*Outcome()
 * in this file. */
export async function resolveCancelAnalysisJobOutcome(
  response: Response | null,
): Promise<CancelAnalysisJobOutcome> {
  if (!response) {
    return { kind: "error", message: JOB_CANCEL_GENERIC_ERROR_MESSAGE };
  }

  if (response.status === 401) {
    return { kind: "unauthorized", message: JOB_CANCEL_UNAUTHORIZED_MESSAGE };
  }

  if (response.status === 403) {
    return { kind: "forbidden", message: JOB_CANCEL_FORBIDDEN_MESSAGE };
  }

  if (response.status === 404) {
    return { kind: "notFound", message: JOB_CANCEL_NOT_FOUND_MESSAGE };
  }

  if (response.status === 409) {
    return { kind: "conflict", message: JOB_CANCEL_CONFLICT_MESSAGE };
  }

  if (!response.ok) {
    return { kind: "error", message: JOB_CANCEL_GENERIC_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  if (!json || (json as { cancelled?: unknown }).cancelled !== true) {
    return { kind: "error", message: JOB_CANCEL_GENERIC_ERROR_MESSAGE };
  }

  return { kind: "cancelled" };
}

// --- failed-job display classification (feature/async-job-failure-display-and-retry) ---
//
// GET /api/analysis-jobs/{id}'s `errorMessage` is, by construction on
// the backend side, always one of exactly three kinds of string (see
// services/analysis_job_worker.py's process_one_job() and
// services/analysis_history_repository.py's
// fail_expired_running_analysis_runs()) — never a raw caught
// exception, stack trace, API key, or internal connection detail:
//
// 1. An input-validation message (AnalysisPipelineInputError, e.g.
//    "urls must not be empty") — the exact same short, user-facing
//    text POST /analyze has always returned as a 400 for the same
//    problem.
// 2. The fixed string below when the pipeline raised an unexpected
//    exception — the real exception is logged server-side only, never
//    persisted to error_message or returned by any API.
// 3. The fixed string below when a worker's lease expired before it
//    finished (fail_expired_running_analysis_runs()) — the worker
//    that held the job may have crashed or been reaped mid-flight, so
//    this is the one case worth explaining further: an external paid
//    API call this job's pipeline had already made before dying is
//    not undone, and this job is never auto-retried (see docs/40
//    "11.4").
//
// classifyJobFailure() tells these apart by exact string match (safe
// here specifically because the backend only ever writes one of these
// three kinds of string — this is not a heuristic over arbitrary
// user-controlled text). Anything else non-empty is treated as
// "validation" (safe to show verbatim, same as before this task);
// absent entirely is "unknown" (the pre-existing generic
// JOB_STATUS_FAILED_BODY already covers this — "原因不明時の汎用
// メッセージ").
const JOB_LEASE_EXPIRED_ERROR_MESSAGE_RAW =
  "worker lease expired (possible partial execution, not auto-retried)";
const JOB_UNEXPECTED_ERROR_MESSAGE_RAW = "unexpected error while running analysis";

export type JobFailureCategory = "leaseExpired" | "unexpected" | "validation" | "unknown";

export function classifyJobFailure(errorMessage: string | undefined): JobFailureCategory {
  if (!errorMessage) return "unknown";
  if (errorMessage === JOB_LEASE_EXPIRED_ERROR_MESSAGE_RAW) return "leaseExpired";
  if (errorMessage === JOB_UNEXPECTED_ERROR_MESSAGE_RAW) return "unexpected";
  return "validation";
}

export const JOB_FAILED_LEASE_EXPIRED_EXPLANATION =
  "処理中に担当のワーカーが応答を失い、分析が中断しました。外部APIの呼び出しが一部完了している可能性があります。安全のため自動的な再試行は行われません。再分析が必要な場合は、下から新しい分析を開始してください。";
export const JOB_FAILED_UNEXPECTED_EXPLANATION = "処理中に予期しないエラーが発生しました。";
export const JOB_FAILED_VALIDATION_LABEL = "入力内容の確認が必要です:";

// --- manual re-analysis from a saved inputSnapshot (same task) -------------
//
// Shared by both the failed-job progress page (app/analysis/jobs/[id]/
// page.tsx) and the completed/partial history detail page
// (app/history/[id]/page.tsx) — "re-run with the same input" is
// exactly the same operation regardless of which screen triggers it:
// read the saved analysis_runs.input_snapshot, generate a fresh
// idempotency key (never reuse the original job/run's — this is a
// deliberate new "start analysis" operation, not a replay), and POST
// /api/analysis-jobs. The actual submission result is interpreted by
// the existing resolveCreateAnalysisJobOutcome() above — no new
// resolver needed, since POST /api/analysis-jobs' response shape is
// identical either way.

export type RetryAnalysisInputPreview = {
  brandName: string;
  inputKind: "documents" | "urls";
  inputCount: number;
  aiOverviewMode?: string;
  chatgptMode?: string;
  claudeMode?: string;
  geminiMode?: string;
  commonCrawlMode?: string;
};

function readOptionalStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  if (!value.every((entry): entry is string => typeof entry === "string")) return undefined;
  return value;
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

/**
 * Decides whether one saved `input_snapshot` has enough information
 * to safely re-submit as a new analysis, and if so, what to show the
 * user before they confirm (brandName/input kind+count/provider
 * modes) — this task's "再分析前にブランド名・入力種別・provider mode
 * を確認できる". Returns null when it doesn't — this task's "input
 * Snapshotに必要なデータが不足する古い履歴は再分析不可として分かり
 * やすく案内する":
 *
 * - every row this app has ever written has `brandName` — a missing
 *   or blank one means the snapshot itself is unusable, full stop.
 * - a job-created row (services/analysis_history_repository.py's
 *   _canonicalize_job_input()) always has an explicit `documents` key
 *   (even `[]`, a legitimate "0 real documents" request — see this
 *   project's documents:[]-is-allowed convention) — that key being a
 *   real array at all is reliable evidence of what the original
 *   request actually was, so it's trusted outright, empty or not.
 * - a row saved by the existing *synchronous* /analyze path
 *   (backend/main.py's save_analysis_history() call site) never
 *   writes a `documents` key at all, regardless of whether the
 *   original request used `documents` or `urls` — so for those rows,
 *   a non-empty `urls` array is trusted (the common case, and
 *   unambiguous), but an *absent or empty* `urls` with no `documents`
 *   key is treated as "can't tell" (the original could have used
 *   `documents`, now unrecoverable, or relied on the backend's
 *   development-sample fallback) rather than guessed at — silently
 *   retrying with no input at all would not reproduce "the same
 *   analysis", so this case refuses rather than risk that.
 */
export function parseRetryableAnalysisInput(
  inputSnapshot: Record<string, unknown> | undefined,
): RetryAnalysisInputPreview | null {
  if (!inputSnapshot) return null;

  const brandName = readOptionalString(inputSnapshot.brandName);
  if (!brandName) return null;

  const documents = readOptionalStringArray(inputSnapshot.documents);
  const urls = readOptionalStringArray(inputSnapshot.urls);

  let inputKind: "documents" | "urls";
  let inputCount: number;
  if (documents !== undefined) {
    inputKind = "documents";
    inputCount = documents.length;
  } else if (urls !== undefined && urls.length > 0) {
    inputKind = "urls";
    inputCount = urls.length;
  } else {
    return null;
  }

  return {
    brandName,
    inputKind,
    inputCount,
    aiOverviewMode: readOptionalString(inputSnapshot.aiOverviewMode),
    chatgptMode: readOptionalString(inputSnapshot.chatgptMode),
    claudeMode: readOptionalString(inputSnapshot.claudeMode),
    geminiMode: readOptionalString(inputSnapshot.geminiMode),
    commonCrawlMode: readOptionalString(inputSnapshot.commonCrawlMode),
  };
}

/** True when the preview's recorded provider modes include anything
 * other than off/mock/unset — used only to decide UI emphasis
 * (whether to show the payment caution more prominently). This can
 * never be a precise prediction of whether a paid call will actually
 * happen (that also depends on the backend's ALLOW_*_MODE_OVERRIDE
 * env state, which the frontend has no way to know — see
 * docs/41_async_analysis_production_rollout.md "3.0") — the caution
 * message itself (RETRY_CONFIRM_MESSAGE below) is shown unconditionally
 * regardless of this, precisely because it can't be known for certain
 * either way. */
export function retryMayCallPaidProvider(preview: RetryAnalysisInputPreview): boolean {
  return [preview.aiOverviewMode, preview.chatgptMode, preview.claudeMode, preview.geminiMode].some(
    (mode) => mode !== undefined && mode !== "off" && mode !== "mock",
  );
}

/** POST /api/analysis-jobs body for a manual retry — mirrors
 * backend's AnalysisJobCreateRequest exactly (unlike
 * AnalysisJobCreateRequestBody above, this supports `documents` too,
 * since a retried inputSnapshot may have used either). */
export interface RetryAnalysisJobRequestBody {
  projectId: string;
  idempotencyKey: string;
  brandName: string;
  documents?: string[];
  urls?: string[];
  aiOverviewMode?: string;
  chatgptMode?: string;
  commonCrawlMode?: string;
  commonCrawlDomain?: string;
  claudeMode?: string;
  geminiMode?: string;
}

/** Builds the retry request body straight from the saved
 * `inputSnapshot` — call only after parseRetryableAnalysisInput()
 * returned non-null for the same snapshot. Always generates a fresh
 * idempotency key (never the original job/run's own) unless one is
 * explicitly passed (tests only) — this is deliberately a new "start
 * analysis" operation, not a replay of the old one, so it must never
 * collide with (or be confused for a resubmission of) the original
 * key. */
export function buildRetryAnalysisJobRequestBody(
  inputSnapshot: Record<string, unknown>,
  projectId: string,
  idempotencyKey: string = generateIdempotencyKey(),
): RetryAnalysisJobRequestBody {
  const body: RetryAnalysisJobRequestBody = {
    projectId,
    idempotencyKey,
    brandName: readOptionalString(inputSnapshot.brandName) ?? "",
  };

  const documents = readOptionalStringArray(inputSnapshot.documents);
  const urls = readOptionalStringArray(inputSnapshot.urls);
  if (documents !== undefined) {
    body.documents = documents;
  } else if (urls !== undefined) {
    body.urls = urls;
  }

  const aiOverviewMode = readOptionalString(inputSnapshot.aiOverviewMode);
  if (aiOverviewMode) body.aiOverviewMode = aiOverviewMode;
  const chatgptMode = readOptionalString(inputSnapshot.chatgptMode);
  if (chatgptMode) body.chatgptMode = chatgptMode;
  const claudeMode = readOptionalString(inputSnapshot.claudeMode);
  if (claudeMode) body.claudeMode = claudeMode;
  const geminiMode = readOptionalString(inputSnapshot.geminiMode);
  if (geminiMode) body.geminiMode = geminiMode;
  const commonCrawlMode = readOptionalString(inputSnapshot.commonCrawlMode);
  if (commonCrawlMode) body.commonCrawlMode = commonCrawlMode;
  const commonCrawlDomain = readOptionalString(inputSnapshot.commonCrawlDomain);
  if (commonCrawlDomain) body.commonCrawlDomain = commonCrawlDomain;

  return body;
}

export const RETRY_BUTTON_LABEL = "同じ条件で再分析する";
export const RETRY_CONFIRM_MESSAGE =
  "同じ条件で新しい分析を開始しますか？設定によっては外部の有料APIが再度呼び出される場合があります。";
export const RETRY_PENDING_TEXT = "再分析を開始しています...";
export const RETRY_NOT_RETRYABLE_MESSAGE =
  "この履歴は保存されている入力情報が不足しているため、同じ条件での再分析はできません。";
export const RETRY_DISABLED_BY_FLAG_MESSAGE =
  "現在、新しい分析の作成は一時的に無効化されています。既存の分析結果の確認・取り消しは引き続き利用できます。";

/**
 * The full "submit a retry" operation, shared verbatim by both
 * callers (the failed-job progress page and the completed/partial
 * history detail page — this task's "再分析の共通ロジックを作成") so
 * neither reimplements the request body shape or the response
 * interpretation. Builds a fresh idempotency key every call (never
 * passed in), POSTs to the existing /api/analysis-jobs proxy, and
 * interprets the response with the exact same
 * resolveCreateAnalysisJobOutcome() the original "start analysis" flow
 * (app/page.tsx) uses — there is nothing retry-specific about how the
 * response is interpreted, only about how the request body is built
 * (from a saved inputSnapshot instead of the input form).
 */
export async function submitRetryAnalysis(
  inputSnapshot: Record<string, unknown>,
  projectId: string,
): Promise<CreateAnalysisJobOutcome> {
  const body = buildRetryAnalysisJobRequestBody(inputSnapshot, projectId);

  const response = await fetch("/api/analysis-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => null);

  return resolveCreateAnalysisJobOutcome(response);
}
