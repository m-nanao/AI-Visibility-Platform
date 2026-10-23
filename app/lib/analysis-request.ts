import type {
  AiOverviewProviderMode,
  ChatGptProviderMode,
  ClaudeProviderMode,
  CommonCrawlProviderMode,
  GeminiProviderMode,
} from "./types";

// The dev/verification-only "AI Overview取得モード" selector
// (BrandInputForm.tsx) is shown only when this is exactly "true". This
// is a UI-visibility flag only — it cannot make DataForSEO run by
// itself. Whether a submitted aiOverviewMode is actually honored is
// still decided entirely server-side by the Python API's
// ALLOW_AI_OVERVIEW_MODE_OVERRIDE (see backend/services/ai_overview_provider.py);
// with that unset/false, the Python API ignores aiOverviewMode
// regardless of what this flag or the UI send.
export function isAiOverviewModeSelectorEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR === "true";
}

// Frontend-side counterpart to the backend's ANALYZE_AUTH_REQUIRED
// (Task 6-B2, feature/sync-analyze-jwt-project-auth) — deliberately a
// *separate* flag, not read from the backend's own setting: this one
// only controls whether app/page.tsx's sync analysis screen resolves/
// shows a project selector and gates submission on being signed in,
// exactly like NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS already does for the
// async flow. The actual JWT/project forwarding in
// app/api/analyze/route.ts happens unconditionally regardless of this
// flag (see that file), so the two flags can safely be flipped in
// either order without ever breaking the sync analysis screen:
//
// - Both false (this task's shipped default): today's anonymous
//   screen, unchanged.
// - This flag true, backend's ANALYZE_AUTH_REQUIRED still false: the
//   screen requires sign-in/project selection in the UI, but the
//   backend still accepts (and would still accept) an anonymous
//   request too — a stricter UI than the backend requires, never the
//   reverse, so this ordering is always safe to ship first.
// - Backend's ANALYZE_AUTH_REQUIRED turned on only *after* this flag
//   has shipped and been verified — never the other way around, or a
//   signed-out/no-project visitor would hit a confusing 401/403 with
//   no corresponding UI to explain it.
export function isAnalyzeAuthRequiredEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED === "true";
}

// Same idea as isAiOverviewModeSelectorEnabled(), for the dev/
// verification-only "ChatGPT観測モード" selector. This flag only
// controls whether the select renders — it cannot make the Python API
// call OpenAI by itself. Whether a submitted chatgptMode is actually
// honored is still decided server-side by ALLOW_CHATGPT_MODE_OVERRIDE
// (see backend/services/chatgpt_provider.py), and even then only when
// aiOverviewMode isn't "mock" (see backend/main.py).
export function isChatGptModeSelectorEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR === "true";
}

// Same idea again, for the dev/verification-only "Common Crawl補完
// （検証用）" selector. This flag only controls whether the select
// renders — it cannot make the Python API contact Common Crawl by
// itself. Whether a submitted commonCrawlMode="domain" actually does
// anything still depends entirely on the backend's
// COMMON_CRAWL_ENABLED (see backend/main.py) — unlike
// aiOverviewMode/chatgptMode there is no separate ALLOW_*_OVERRIDE gate
// for this one (see backend/models.py's CommonCrawlProviderMode
// docstring for why that's still safe).
export function isCommonCrawlModeSelectorEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR === "true";
}

// Same idea again, for the dev/verification-only "Claude観測モード"
// selector. This flag only controls whether the select renders — it
// cannot make the Python API call Anthropic by itself. Whether a
// submitted claudeMode is actually honored is still decided
// server-side by ALLOW_CLAUDE_MODE_OVERRIDE (see
// backend/services/claude_provider.py). Unlike chatgptMode, this is
// NOT skipped when aiOverviewMode is "mock" — see
// backend/services/claude_provider.py's module docstring for why
// (there's no colliding "Claude" mock card to avoid duplicating).
export function isClaudeModeSelectorEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR === "true";
}

// Same idea again, for the dev/verification-only "Gemini観測モード"
// selector. This flag only controls whether the select renders — it
// cannot make the Python API call Gemini by itself. Whether a
// submitted geminiMode is actually honored is still decided
// server-side by ALLOW_GEMINI_MODE_OVERRIDE (see
// backend/services/gemini_provider.py). Like claudeMode (and unlike
// chatgptMode), this is NOT skipped when aiOverviewMode is "mock" —
// see backend/services/gemini_provider.py's module docstring for why
// (there's no colliding "Gemini" mock card to avoid duplicating).
export function isGeminiModeSelectorEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR === "true";
}

export interface AnalyzeRequestBody {
  brandName: string;
  urls?: string[];
  aiOverviewMode?: AiOverviewProviderMode;
  chatgptMode?: ChatGptProviderMode;
  commonCrawlMode?: CommonCrawlProviderMode;
  commonCrawlDomain?: string;
  claudeMode?: ClaudeProviderMode;
  geminiMode?: GeminiProviderMode;
  // The project to save this analysis under — only meaningful once
  // app/api/analyze/route.ts's backend counterpart
  // (ANALYZE_AUTH_REQUIRED=true) actually requires it; omitted
  // entirely when the caller has no project to send (e.g. the
  // existing anonymous flow, or ANALYZE_AUTH_REQUIRED=false in
  // production today) — see Task 6-B2
  // (feature/sync-analyze-jwt-project-auth).
  // Task 6-D-5B (feature/official-info-candidate) — mirrors
  // backend/models.py's AnalyzeRequest.officialUrl exactly. Always
  // sent exactly as the user typed it (trimmed, non-blank) — never
  // auto-detected, never merged into `urls` above.
  officialUrl?: string;
  projectId?: string;
  // Idempotency key for the synchronous analysis itself (Task 6-B3,
  // feature/sync-analyze-jwt-project-auth) — only meaningful (and only
  // ever sent, see app/page.tsx) once ANALYZE_AUTH_REQUIRED=true, since
  // the backend's DB-level idempotency enforcement is scoped to the
  // authenticated path only (see
  // backend/services/analysis_history_repository.py's module comment
  // for why: the existing unique index can't enforce anything when
  // created_by_user_id is NULL, as every anonymous request's is).
  // Omitted entirely for the anonymous flow, exactly like projectId
  // above.
  requestId?: string;
}

/**
 * Builds the POST /api/analyze request body. `urls`/`aiOverviewMode`/
 * `chatgptMode`/`commonCrawlMode`/`commonCrawlDomain`/`claudeMode`/
 * `geminiMode` are omitted entirely (not sent as
 * `[]`/`undefined`/`"off"`/empty-string values) rather than included
 * with an empty/default value — the Next.js and Python APIs both
 * treat an omitted key as "use the default", so a normal submission
 * (no urls, no mode selector shown) produces exactly the same body it
 * always has. `commonCrawlMode` follows this same omit-the-default
 * pattern as aiOverviewMode/chatgptMode — omitting "off" is
 * behaviorally identical to sending it explicitly, since the backend
 * already treats an omitted commonCrawlMode as "off" (see
 * backend/main.py). `claudeMode`/`geminiMode` mirror chatgptMode's own
 * pattern exactly: included whenever passed (even "off"), omitted
 * only when the selector isn't shown at all.
 */
export function buildAnalyzeRequestBody(
  brandName: string,
  urls: string[],
  aiOverviewMode?: AiOverviewProviderMode,
  chatgptMode?: ChatGptProviderMode,
  commonCrawlMode?: CommonCrawlProviderMode,
  commonCrawlDomain?: string,
  claudeMode?: ClaudeProviderMode,
  geminiMode?: GeminiProviderMode,
  projectId?: string,
  requestId?: string,
  officialUrl?: string,
): AnalyzeRequestBody {
  const body: AnalyzeRequestBody = { brandName };
  if (urls.length > 0) body.urls = urls;
  if (aiOverviewMode) body.aiOverviewMode = aiOverviewMode;
  if (chatgptMode) body.chatgptMode = chatgptMode;
  if (commonCrawlMode && commonCrawlMode !== "off") body.commonCrawlMode = commonCrawlMode;
  if (commonCrawlDomain && commonCrawlDomain.trim()) {
    body.commonCrawlDomain = commonCrawlDomain.trim();
  }
  if (claudeMode) body.claudeMode = claudeMode;
  if (geminiMode) body.geminiMode = geminiMode;
  if (projectId && projectId.trim()) body.projectId = projectId.trim();
  if (requestId && requestId.trim()) body.requestId = requestId.trim();
  if (officialUrl && officialUrl.trim()) body.officialUrl = officialUrl.trim();
  return body;
}

// --- requestId generation/persistence (Task 6-B3,
// feature/sync-analyze-jwt-project-auth) --------------------------------
//
// Mirrors app/lib/analysis-jobs.ts's own idempotency-key management
// for the async flow exactly (same sessionStorage-backed "reuse for a
// retry of the same input, fresh one for genuinely new input"
// pattern, see that file's module comment for the full reasoning) —
// kept as a separate storage key/namespace here rather than sharing
// code, since the sync and async flows are entirely separate
// submissions that must never see or clear each other's pending key.

const PENDING_SYNC_ANALYSIS_STORAGE_KEY = "sync-analyze-pending-request";

type PendingSyncAnalysisRecord = { requestId: string; inputHash: string };

function hashSyncAnalysisInput(
  userScope: string,
  projectId: string,
  content: AnalyzeRequestBody,
): string {
  return JSON.stringify({ userScope, projectId, content });
}

function readPendingSyncAnalysis(): PendingSyncAnalysisRecord | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(PENDING_SYNC_ANALYSIS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as PendingSyncAnalysisRecord).requestId === "string" &&
      typeof (parsed as PendingSyncAnalysisRecord).inputHash === "string"
    ) {
      return parsed as PendingSyncAnalysisRecord;
    }
    return null;
  } catch {
    return null;
  }
}

function writePendingSyncAnalysis(record: PendingSyncAnalysisRecord): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      PENDING_SYNC_ANALYSIS_STORAGE_KEY,
      JSON.stringify(record),
    );
  } catch {
    // Not fatal — the id generated this call is still returned and
    // used for this request.
  }
}

/** Generates a fresh, random requestId. Separated from
 * resolveRequestIdForSyncAnalysis() below so a test can inject a
 * deterministic generator instead of depending on
 * `crypto.randomUUID()`. Must stay within _REQUEST_ID_PATTERN's
 * allowed character set on the backend (letters/digits/hyphen/
 * underscore) — crypto.randomUUID()'s hyphenated hex format already
 * satisfies that. */
export function generateRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `fallback-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Resolves the requestId to use for a synchronous "分析開始"
 * submission with the given `userScope`/`projectId`/`content` —
 * reusing a previously stored id if (and only if) it was generated for
 * the exact same input, otherwise generating and persisting a new one.
 * Mirrors app/lib/analysis-jobs.ts's resolveIdempotencyKeyForJobSubmission()
 * exactly (see that function's doc for the full `userScope` reasoning).
 */
export function resolveRequestIdForSyncAnalysis(
  userScope: string,
  projectId: string,
  content: AnalyzeRequestBody,
  generateId: () => string = generateRequestId,
): string {
  const inputHash = hashSyncAnalysisInput(userScope, projectId, content);
  const existing = readPendingSyncAnalysis();
  if (existing && existing.inputHash === inputHash) {
    return existing.requestId;
  }

  const requestId = generateId();
  writePendingSyncAnalysis({ requestId, inputHash });
  return requestId;
}

/**
 * Clears the stored pending sync-analysis requestId record — called
 * once a submission reaches a definitive outcome (success, or the
 * input/request was rejected outright, or the previous analysis for
 * this requestId is in a terminal state the user must not retry) so
 * the *next* explicit "分析開始" click always gets a brand-new
 * requestId. Deliberately NOT called when the server reports the
 * analysis is still running, or on a network-level failure — those are
 * exactly the cases where a resubmission should reuse the same
 * requestId (see app/page.tsx's call sites).
 */
export function clearPendingSyncAnalysisRequest(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(PENDING_SYNC_ANALYSIS_STORAGE_KEY);
  } catch {
    // ignore
  }
}

// --- POST /api/analyze auth errors (Task 6-B2,
// feature/sync-analyze-jwt-project-auth) --------------------------------
//
// Only reachable once ANALYZE_AUTH_REQUIRED=true on the backend (still
// false in production as of this task) — app/api/analyze/route.ts
// forwards these as real 401/403 responses rather than ever folding
// them into the dummy-data fallback (see that file's PythonApiOutcome
// "authError" kind) — an auth/authorization failure must never look
// like a successful (if "mock") analysis.

export const ANALYZE_AUTH_REQUIRED_MESSAGE = "ログインが必要です。";
export const ANALYZE_ACCESS_DENIED_MESSAGE = "このprojectで分析を実行する権限がありません。";
// Shown by the Frontend input screen itself (before even submitting)
// when GET /api/me/projects resolves to zero accessible projects.
export const ANALYZE_PROJECT_ID_REQUIRED_MESSAGE =
  "分析を実行するprojectを選択してください。";
export const ANALYZE_AUTH_CONFIG_ERROR_MESSAGE =
  "認証の設定に問題があるため、分析を実行できません。時間をおいて再度お試しください。";

// --- POST /api/analyze idempotency conflicts (Task 6-B3,
// feature/sync-analyze-jwt-project-auth) --------------------------------
//
// Only reachable once ANALYZE_AUTH_REQUIRED=true (same precondition as
// the auth errors above) — these are the 4 distinct 409 causes
// backend/main.py's _analyze_authenticated_idempotent() can return,
// distinguished by the stable `code` field on the response body
// (never by matching error prose — same reasoning as
// ANALYZE_AUTH_UNAVAILABLE_CODE in app/api/analyze/route.ts).

/** Must match backend/main.py's ANALYZE_STILL_RUNNING_CODE. */
export const ANALYZE_STILL_RUNNING_CODE = "analysis_still_running";
/** Must match backend/main.py's ANALYZE_PREVIOUSLY_FAILED_CODE. */
export const ANALYZE_PREVIOUSLY_FAILED_CODE = "analysis_previously_failed";
/** Must match backend/main.py's ANALYZE_REQUEST_CONFLICT_CODE. */
export const ANALYZE_REQUEST_CONFLICT_CODE = "analysis_request_conflict";
/** Must match backend/main.py's ANALYZE_REQUEST_CANCELLED_CODE. */
export const ANALYZE_REQUEST_CANCELLED_CODE = "analysis_request_cancelled";

export const ANALYZE_STILL_RUNNING_MESSAGE =
  "この分析はまだ処理中です。しばらくしてから再度お試しください。";
export const ANALYZE_PREVIOUSLY_FAILED_MESSAGE =
  "直前の分析は失敗しました。もう一度最初から分析を開始してください。";
export const ANALYZE_REQUEST_CONFLICT_MESSAGE =
  "直前の分析開始操作と内容が異なります。入力を確認して再度お試しください。";
export const ANALYZE_REQUEST_CANCELLED_MESSAGE =
  "この分析は削除済みのため再利用できません。もう一度最初から分析を開始してください。";
export const ANALYZE_CONFLICT_GENERIC_MESSAGE =
  "分析を開始できませんでした。時間をおいて再度お試しください。";

const ANALYZE_CONFLICT_CODE_MESSAGES: Record<string, string> = {
  [ANALYZE_STILL_RUNNING_CODE]: ANALYZE_STILL_RUNNING_MESSAGE,
  [ANALYZE_PREVIOUSLY_FAILED_CODE]: ANALYZE_PREVIOUSLY_FAILED_MESSAGE,
  [ANALYZE_REQUEST_CONFLICT_CODE]: ANALYZE_REQUEST_CONFLICT_MESSAGE,
  [ANALYZE_REQUEST_CANCELLED_CODE]: ANALYZE_REQUEST_CANCELLED_MESSAGE,
};

/** Turns a POST /api/analyze 409 response's `code` (or null, when
 * missing/unrecognized) into a safe-to-display message. */
export function getAnalyzeConflictMessage(code: string | null): string {
  if (code && code in ANALYZE_CONFLICT_CODE_MESSAGES) {
    return ANALYZE_CONFLICT_CODE_MESSAGES[code];
  }
  return ANALYZE_CONFLICT_GENERIC_MESSAGE;
}

/** True only for the 409 causes that mean "this exact requestId can
 * never be retried" (previously failed / input conflict / cancelled)
 * — app/page.tsx clears the stored pending requestId for these so the
 * next explicit "分析開始" click gets a fresh one. False for
 * ANALYZE_STILL_RUNNING_CODE, where the same requestId should be kept
 * so a later resubmission (once the analysis actually finishes) can
 * still reuse it. */
export function isTerminalAnalyzeConflictCode(code: string | null): boolean {
  return (
    code === ANALYZE_PREVIOUSLY_FAILED_CODE ||
    code === ANALYZE_REQUEST_CONFLICT_CODE ||
    code === ANALYZE_REQUEST_CANCELLED_CODE
  );
}

// --- POST /api/analyze usage-quota (Task 6-B4,
// feature/sync-analyze-jwt-project-auth) --------------------------------
//
// Only reachable once ANALYZE_AUTH_REQUIRED=true *and*
// ANALYZE_QUOTA_ENFORCEMENT_ENABLED=true on the backend (both still
// false in production as of this task). A 429 here means no
// analysis_runs row was created at all — unlike the 409 conflict
// codes above, the requestId is safe (and, per this task's design
// report, expected) to keep for a later retry, since nothing exists
// yet for the backend to disagree about; app/page.tsx therefore never
// clears the pending requestId on this outcome. Detailed UI (showing
// `availableAt`, a countdown, etc.) is deferred to Task 6-B5 — this
// is the minimal "don't crash, don't mislead" handling this task asks
// for.

/** Must match backend/main.py's ANALYZE_QUOTA_EXCEEDED_CODE. */
export const ANALYZE_QUOTA_EXCEEDED_CODE = "analysis_quota_exceeded";
export const ANALYZE_QUOTA_EXCEEDED_MESSAGE =
  "利用上限に達しているため、分析を開始できません。時間をおいて再度お試しください。";

/** The `quota` object a 429 analysis_quota_exceeded response body
 * carries — see backend/main.py's _analyze_authenticated_idempotent().
 * Any field may be absent/malformed if the response shape ever
 * drifts; callers must not assume it's present. */
export interface AnalyzeQuotaInfo {
  scope?: string;
  metric?: string;
  period?: string;
  availableAt?: string;
}

// --- POST /api/analyze dummy-fallback signaling (shared between
// app/api/analyze/route.ts and app/page.tsx, since a Next.js route
// handler module may only export HTTP method handlers plus a small set
// of framework-recognized names — arbitrary named constants exported
// from route.ts are not importable elsewhere, so these live here
// instead). See app/api/analyze/route.ts's PYTHON_API_TIMEOUT_MS
// comment for the full background: with every verification selector
// on at once, the Python API can legitimately take longer than this
// route is willing to wait, in which case it falls back to dummy data
// here *while the Python API keeps running and may still save a real
// result to history* — these headers let app/page.tsx tell a依頼者
// that what they're looking at is a fallback, not the real analysis.

/** Present (value "1") only on a dummy-fallback /api/analyze response — absent on a real one. */
export const ANALYZE_FALLBACK_HEADER = "X-Analyze-Fallback";
/** Why the fallback happened — see PythonApiUnavailableReason in app/api/analyze/route.ts. */
export const ANALYZE_FALLBACK_REASON_HEADER = "X-Analyze-Fallback-Reason";

const ANALYZE_FALLBACK_REASON_MESSAGES: Record<string, string> = {
  // Reworded per improve/history-centered-analysis-flow — the old
  // wording called the dummy data "開発用データ", which reads as if
  // this screen were a dev/test artifact rather than a normal (if
  // temporarily incomplete) analysis attempt. "一時的なプレビュー"
  // matches this task's broader framing of the analysis result screen
  // as a preview, with the history list screen as where the real,
  // saved result can be found once the backend finishes.
  timeout:
    "分析の取得に時間がかかったため、この画面では一時的なプレビューを表示しています。分析自体は裏側で完了し、履歴に保存されている場合があります。しばらくしてから履歴一覧を確認してください。",
  not_configured:
    "分析APIが設定されていないため、開発用データを表示しています。",
  request_failed:
    "分析結果の取得に失敗したため、開発用データを表示しています。",
  upstream_error:
    "分析結果の取得に失敗したため、開発用データを表示しています。",
  invalid_json:
    "分析結果の取得に失敗したため、開発用データを表示しています。",
  schema_mismatch:
    "分析結果の取得に失敗したため、開発用データを表示しています。",
};

const ANALYZE_FALLBACK_DEFAULT_MESSAGE =
  "分析結果の取得に失敗したため、開発用データを表示しています。";

/**
 * Turns the ANALYZE_FALLBACK_REASON_HEADER value (or null, when the
 * header wasn't an expected key) into a safe-to-display message — used
 * by app/page.tsx to explain a dummy-data result without the route
 * handler needing to know anything about UI copy. Falls back to a
 * generic message for an unrecognized/missing reason rather than
 * showing nothing at all, since ANALYZE_FALLBACK_HEADER being present
 * at all already means a fallback happened.
 */
export function getAnalyzeFallbackMessage(reason: string | null): string {
  if (reason && reason in ANALYZE_FALLBACK_REASON_MESSAGES) {
    return ANALYZE_FALLBACK_REASON_MESSAGES[reason];
  }
  return ANALYZE_FALLBACK_DEFAULT_MESSAGE;
}
