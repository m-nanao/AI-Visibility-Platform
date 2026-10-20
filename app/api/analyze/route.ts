import { NextResponse } from "next/server";
import { buildDummyAnalysis } from "../../lib/dummy-data";
import { parseAnalysisResult } from "../../lib/analysis-result-schema";
import {
  ANALYZE_ACCESS_DENIED_MESSAGE,
  ANALYZE_AUTH_CONFIG_ERROR_MESSAGE,
  ANALYZE_AUTH_REQUIRED_MESSAGE,
  ANALYZE_FALLBACK_HEADER,
  ANALYZE_FALLBACK_REASON_HEADER,
} from "../../lib/analysis-request";
import { getServerSupabaseAccessToken } from "../../lib/supabase/server";
import type {
  AiOverviewProviderMode,
  AnalysisResult,
  ChatGptProviderMode,
  ClaudeProviderMode,
  CommonCrawlProviderMode,
  GeminiProviderMode,
} from "../../lib/types";

const AI_OVERVIEW_MODES: readonly AiOverviewProviderMode[] = [
  "mock",
  "off",
  "dataforseo",
  "dataforseo_sandbox",
  "dataforseo_live",
];
const CHATGPT_MODES: readonly ChatGptProviderMode[] = ["off", "openai"];
const COMMON_CRAWL_MODES: readonly CommonCrawlProviderMode[] = ["off", "domain"];
const CLAUDE_MODES: readonly ClaudeProviderMode[] = ["off", "anthropic"];
const GEMINI_MODES: readonly GeminiProviderMode[] = ["off", "google"];

const SIMULATED_ANALYSIS_DELAY_MS = 900;

// When `urls` is set, the Python API fetches up to MAX_URLS(10) pages
// with limited concurrency (3 at a time, ~5s timeout each — see
// backend/services/web_fetcher.py), so a slow/degraded batch of
// fetches can legitimately take up to ~ceil(10/3) * 5s = 20s before
// Python can respond.
//
// On top of that, every AI observation/Common Crawl provider is called
// *sequentially* by backend/main.py, each with its own per-request
// timeout: DataForSEO ~12s, ChatGPT/Claude/Gemini ~20s each, Common
// Crawl ~10s (see each service's own REQUEST_TIMEOUT_SECONDS /
// DEFAULT_TIMEOUT_SECONDS — not changed here). With every verification
// selector turned on at once (AI Overview=DataForSEO Live, ChatGPT,
// Claude, Gemini, Common Crawl all ON), a request that previously only
// waited on URL fetching now also waits on up to 5 more sequential
// external calls — comfortably exceeding the old 25s budget even
// though each individual call finishes well under its own timeout.
//
// When that happened, this route's AbortController fired at 25s and
// returned the dummy fallback below *while the Python API kept running
// to completion in the background* (FastAPI/uvicorn doesn't cancel a
// handler just because the caller disconnected) and successfully saved
// a real result to the DB — which is exactly why the saved history
// entry showed real text while the just-analyzed screen showed dummy
// data for the same request. 55s gives enough headroom for a realistic
// full-ON request (it is not sized for every provider simultaneously
// hitting its own worst-case timeout, which would exceed what any
// reasonable serverless function duration can wait for) while still
// failing fast enough that a genuinely stuck Python API doesn't hang
// the request forever.
const PYTHON_API_TIMEOUT_MS = 55_000;

// Why the "unavailable" (dummy-fallback) outcome happened — attached
// as a response header (never the response body/schema, so this never
// risks breaking AnalysisResult parsing) purely so the caller
// (app/page.tsx) can tell a依頼者 that what they're looking at is a
// fallback, not a real analysis, without this route having to guess at
// UI copy. Never includes the Python API's response body, headers, or
// any secret — see the logging below.
type PythonApiUnavailableReason =
  | "not_configured"
  | "timeout"
  | "request_failed"
  | "upstream_error"
  | "invalid_json"
  | "schema_mismatch";

type PythonApiOutcome =
  | { kind: "success"; data: AnalysisResult }
  // The Python API rejected *our request* (e.g. too many documents,
  // urls: []) — this is the caller's mistake, not a Python API
  // failure, so it must be reported back rather than silently
  // papered over with dummy data.
  | { kind: "validationError"; message: string }
  // Only reachable once the Python API's ANALYZE_AUTH_REQUIRED=true
  // (Task 6-B2, feature/sync-analyze-jwt-project-auth) — missing/
  // invalid JWT (401), inaccessible project (403), or the one specific
  // 503 shape that means "JWT verification/project-access check
  // itself is misconfigured" (see ANALYZE_AUTH_UNAVAILABLE_CODE
  // below). Reported back as a real error, exactly like
  // validationError above — this must NEVER fall through to the
  // dummy-data fallback below, since an auth/authorization failure
  // silently rendered as a successful "mock" analysis would be
  // actively misleading.
  | { kind: "authError"; status: 401 | 403 | 503 }
  // Unset URL, network error, timeout, non-2xx (other than 400/401/403,
  // and 503 only when it isn't the auth-config case above), invalid
  // JSON, or a response that doesn't match AnalysisResult.
  | { kind: "unavailable"; reason: PythonApiUnavailableReason };

// Must match backend/main.py's ANALYZE_AUTH_UNAVAILABLE_CODE exactly —
// the stable, machine-readable `code` (see that file's error_response())
// a 503 carries when it specifically means "JWT verification/
// project-access check is misconfigured" (an authError, never
// dummy-fallback-worthy), as opposed to the Python API's own,
// unrelated 503 causes (not configured / DB unreachable — the
// existing "unavailable" fallback path, unchanged). Checking this
// fixed `code` field (added by Task 7,
// feature/sync-analyze-jwt-project-auth, "エラーメッセージの完全一致に
// 依存する実装を改善する") rather than matching the human-readable
// `error` prose means a future reword of that backend message can
// never silently break this distinction.
const ANALYZE_AUTH_UNAVAILABLE_CODE = "auth_unavailable";

/**
 * Tries the Python analysis API when PYTHON_ANALYSIS_API_URL is configured.
 * Every failure reason is logged (path + message only — never raw payloads
 * or headers, so no secrets end up in server logs).
 */
async function fetchFromPythonApi(
  brandName: string,
  documents?: string[],
  urls?: string[],
  aiOverviewMode?: AiOverviewProviderMode,
  chatgptMode?: ChatGptProviderMode,
  commonCrawlMode?: CommonCrawlProviderMode,
  commonCrawlDomain?: string,
  claudeMode?: ClaudeProviderMode,
  geminiMode?: GeminiProviderMode,
  // Task 6-B2 (feature/sync-analyze-jwt-project-auth) additions —
  // both are always forwarded whenever present, regardless of this
  // app's own knowledge of ANALYZE_AUTH_REQUIRED: the Python API's own
  // flag is what actually decides whether either is required, so
  // sending them unconditionally keeps this route correct whichever
  // way that flag is set, without the two ever needing to agree on a
  // deploy order. When the flag is false (production default as of
  // this task), the Python API ignores both exactly as before they
  // existed.
  projectId?: string,
  accessToken?: string | null,
): Promise<PythonApiOutcome> {
  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) return { kind: "unavailable", reason: "not_configured" };

  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(),
    PYTHON_API_TIMEOUT_MS,
  );

  const requestBody: {
    brandName: string;
    documents?: string[];
    urls?: string[];
    aiOverviewMode?: AiOverviewProviderMode;
    chatgptMode?: ChatGptProviderMode;
    commonCrawlMode?: CommonCrawlProviderMode;
    commonCrawlDomain?: string;
    claudeMode?: ClaudeProviderMode;
    geminiMode?: GeminiProviderMode;
    projectId?: string;
  } = { brandName };
  if (documents) requestBody.documents = documents;
  if (urls) requestBody.urls = urls;
  if (projectId) requestBody.projectId = projectId;
  // Forwarded as-is; the Python API decides whether to actually honor
  // it (ALLOW_AI_OVERVIEW_MODE_OVERRIDE) or ignore it in favor of its
  // own AI_OVERVIEW_PROVIDER_MODE default. Next.js does not gate this
  // itself — it's a pure passthrough field, not yet exposed in the UI.
  if (aiOverviewMode) requestBody.aiOverviewMode = aiOverviewMode;
  // Same passthrough pattern as aiOverviewMode above — the Python API
  // decides whether to actually honor it (ALLOW_CHATGPT_MODE_OVERRIDE),
  // and even then only calls OpenAI when aiOverviewMode isn't "mock"
  // (see backend/main.py). Next.js does not gate this itself.
  if (chatgptMode) requestBody.chatgptMode = chatgptMode;
  // Same passthrough pattern again, for the Common Crawl "補完" flow
  // (see backend/services/common_crawl_index.py /
  // common_crawl_warc.py / common_crawl_document_provider.py). The
  // Python API decides whether to actually honor it
  // (COMMON_CRAWL_ENABLED) — Next.js does not gate this itself, and
  // there is no UI for it yet (API/console verification only).
  if (commonCrawlMode) requestBody.commonCrawlMode = commonCrawlMode;
  if (commonCrawlDomain) requestBody.commonCrawlDomain = commonCrawlDomain;
  // Same passthrough pattern as chatgptMode above, for the Claude
  // observation (see backend/services/claude_provider.py). The Python
  // API decides whether to actually honor it
  // (ALLOW_CLAUDE_MODE_OVERRIDE) — unlike chatgptMode, it is NOT
  // skipped when aiOverviewMode is "mock" (see that module's
  // docstring). Next.js does not gate this itself.
  if (claudeMode) requestBody.claudeMode = claudeMode;
  // Same passthrough pattern as claudeMode above, for the Gemini
  // observation (see backend/services/gemini_provider.py). The Python
  // API decides whether to actually honor it
  // (ALLOW_GEMINI_MODE_OVERRIDE) — like claudeMode, it is NOT skipped
  // when aiOverviewMode is "mock" (see that module's docstring).
  // Next.js does not gate this itself.
  if (geminiMode) requestBody.geminiMode = geminiMode;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    // Always attached whenever a session is present, regardless of
    // this app's own knowledge of ANALYZE_AUTH_REQUIRED — see this
    // function's `accessToken` parameter doc above. Never attaching
    // this only because a local flag is false would otherwise create
    // exactly the "Frontend/Backendのフラグ設定が異なる期間" gap this
    // task was asked to avoid.
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/analyze`, {
      method: "POST",
      headers,
      body: JSON.stringify(requestBody),
      signal: controller.signal,
    });

    if (response.status === 400 || response.status === 422) {
      // Both mean "the request we sent was invalid" (400: our own
      // validation errors like urls: []; 422: FastAPI's default
      // request-validation error shape, in case anything ever bypasses
      // our custom exception handler). Only trust the response body if
      // it's our own known-safe { error: string } shape — anything
      // else (e.g. FastAPI's raw `{ detail: [...] }` array of
      // validator internals) is replaced with a generic message rather
      // than shown to the user as-is.
      const errorBody = await response.json().catch(() => null);
      const message =
        errorBody && typeof errorBody.error === "string"
          ? errorBody.error
          : "入力内容を確認してください";
      return { kind: "validationError", message };
    }

    if (!response.ok) {
      // Task 6-B2: a 401/403 (ANALYZE_AUTH_REQUIRED=true only — never
      // sent by the Python API otherwise) must never fall through to
      // the dummy-data fallback below — an auth/authorization failure
      // silently rendered as a successful "mock" analysis would be
      // actively misleading (this task's explicit requirement).
      if (response.status === 401 || response.status === 403) {
        return { kind: "authError", status: response.status };
      }
      if (response.status === 503) {
        // Distinguishes "JWT verification/project-access check is
        // misconfigured" (also an authError, same reasoning as above)
        // from every other, unrelated 503 cause this route has always
        // treated as a dummy-fallback-worthy "unavailable" outcome
        // (Python API not configured, DB unreachable, etc.) — via the
        // stable `code` field (see ANALYZE_AUTH_UNAVAILABLE_CODE
        // above), never by matching the response's human-readable
        // `error` text.
        const errorBody = await response.json().catch(() => null);
        const code = errorBody && typeof errorBody.code === "string" ? errorBody.code : null;
        if (code === ANALYZE_AUTH_UNAVAILABLE_CODE) {
          return { kind: "authError", status: 503 };
        }
      }
      console.warn(
        `[analyze] Python API returned HTTP ${response.status}; falling back to dummy data`,
      );
      return { kind: "unavailable", reason: "upstream_error" };
    }

    let json: unknown;
    try {
      json = await response.json();
    } catch {
      console.warn(
        "[analyze] Python API returned invalid JSON; falling back to dummy data",
      );
      return { kind: "unavailable", reason: "invalid_json" };
    }

    const parsed = parseAnalysisResult(json);
    if (!parsed.success) {
      console.warn(
        `[analyze] Python API response failed schema validation; falling back to dummy data (${parsed.reason})`,
      );
      return { kind: "unavailable", reason: "schema_mismatch" };
    }

    return { kind: "success", data: parsed.data };
  } catch (err) {
    const isTimeout = err instanceof Error && err.name === "AbortError";
    console.warn(
      `[analyze] Python API ${isTimeout ? "request timed out" : "request failed"}; falling back to dummy data`,
    );
    return { kind: "unavailable", reason: isTimeout ? "timeout" : "request_failed" };
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const brandName = body?.brandName;

  if (typeof brandName !== "string" || !brandName.trim()) {
    return NextResponse.json(
      { error: "brandName is required" },
      { status: 400 },
    );
  }

  const trimmedBrandName = brandName.trim();

  // Optional: an array of documents, or URLs to fetch, to run the
  // (Python-side) co-occurrence analysis on. Omitted/invalid -> forwarded
  // as undefined; the Python API then falls back per its own priority
  // (documents > urls > development sample documents).
  const documents = Array.isArray(body?.documents)
    ? body.documents.filter((doc: unknown): doc is string => typeof doc === "string")
    : undefined;
  const urls = Array.isArray(body?.urls)
    ? body.urls.filter((url: unknown): url is string => typeof url === "string")
    : undefined;
  // Optional per-request override of the aiOverviewComparison provider
  // mode (see backend/services/ai_overview_provider.py). An invalid
  // value here is simply dropped (forwarded as undefined) rather than
  // rejected with 400 — this field doesn't affect any of the
  // already-real sections, and the Python API independently decides
  // whether to honor it at all (ALLOW_AI_OVERVIEW_MODE_OVERRIDE).
  const aiOverviewMode = AI_OVERVIEW_MODES.includes(body?.aiOverviewMode)
    ? (body.aiOverviewMode as AiOverviewProviderMode)
    : undefined;
  // Same pattern as aiOverviewMode above, for the ChatGPT-equivalent
  // observation (see backend/services/chatgpt_provider.py). An invalid
  // value is dropped rather than rejected with 400.
  const chatgptMode = CHATGPT_MODES.includes(body?.chatgptMode)
    ? (body.chatgptMode as ChatGptProviderMode)
    : undefined;
  // Same pattern again, for the Common Crawl "補完" flow (see
  // backend/services/common_crawl_index.py /
  // common_crawl_document_provider.py and
  // docs/13_common_crawl_mvp_design.md). No UI sends these yet — this
  // is reachable only via a direct POST body (API/console
  // verification). An invalid mode is dropped rather than rejected
  // with 400; commonCrawlDomain is forwarded as-is when it's a
  // non-empty string (the Python API validates/normalizes it before
  // ever using it in a request).
  const commonCrawlMode = COMMON_CRAWL_MODES.includes(body?.commonCrawlMode)
    ? (body.commonCrawlMode as CommonCrawlProviderMode)
    : undefined;
  const commonCrawlDomain =
    typeof body?.commonCrawlDomain === "string" && body.commonCrawlDomain.trim()
      ? body.commonCrawlDomain.trim()
      : undefined;
  // Same pattern as chatgptMode above, for the Claude observation (see
  // backend/services/claude_provider.py). An invalid value is dropped
  // rather than rejected with 400.
  const claudeMode = CLAUDE_MODES.includes(body?.claudeMode)
    ? (body.claudeMode as ClaudeProviderMode)
    : undefined;
  // Same pattern as claudeMode above, for the Gemini observation (see
  // backend/services/gemini_provider.py). An invalid value is dropped
  // rather than rejected with 400.
  const geminiMode = GEMINI_MODES.includes(body?.geminiMode)
    ? (body.geminiMode as GeminiProviderMode)
    : undefined;
  // Task 6-B2 (feature/sync-analyze-jwt-project-auth): forwarded as-is
  // whenever present — never trusted by this route itself (it does no
  // access check of its own); the Python API is the one that verifies
  // the caller's JWT actually has access to this exact project before
  // ever using it (see backend/main.py's _resolve_analyze_project_auth()).
  const projectId =
    typeof body?.projectId === "string" && body.projectId.trim()
      ? body.projectId.trim()
      : undefined;
  // Always resolved and forwarded regardless of whether this app knows
  // ANALYZE_AUTH_REQUIRED's current value — see fetchFromPythonApi()'s
  // `accessToken` parameter doc. null when there's no session (an
  // anonymous caller), exactly like every other proxy route in this
  // app that forwards a Supabase access token.
  const accessToken = await getServerSupabaseAccessToken(request);

  const outcome = await fetchFromPythonApi(
    trimmedBrandName,
    documents,
    urls,
    aiOverviewMode,
    chatgptMode,
    commonCrawlMode,
    commonCrawlDomain,
    claudeMode,
    geminiMode,
    projectId,
    accessToken,
  );

  if (outcome.kind === "success") {
    return NextResponse.json(outcome.data);
  }

  if (outcome.kind === "validationError") {
    return NextResponse.json({ error: outcome.message }, { status: 400 });
  }

  if (outcome.kind === "authError") {
    // Never falls back to dummy data — see PythonApiOutcome's
    // "authError" doc above for why.
    const message =
      outcome.status === 401
        ? ANALYZE_AUTH_REQUIRED_MESSAGE
        : outcome.status === 403
          ? ANALYZE_ACCESS_DENIED_MESSAGE
          : ANALYZE_AUTH_CONFIG_ERROR_MESSAGE;
    return NextResponse.json({ error: message }, { status: outcome.status });
  }

  await new Promise((resolve) =>
    setTimeout(resolve, SIMULATED_ANALYSIS_DELAY_MS),
  );

  return NextResponse.json(buildDummyAnalysis(trimmedBrandName), {
    headers: {
      [ANALYZE_FALLBACK_HEADER]: "1",
      [ANALYZE_FALLBACK_REASON_HEADER]: outcome.reason,
    },
  });
}
