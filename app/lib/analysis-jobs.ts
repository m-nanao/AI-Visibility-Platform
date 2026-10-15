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
