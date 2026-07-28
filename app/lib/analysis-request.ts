import type {
  AiOverviewProviderMode,
  ChatGptProviderMode,
  CommonCrawlProviderMode,
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

export interface AnalyzeRequestBody {
  brandName: string;
  urls?: string[];
  aiOverviewMode?: AiOverviewProviderMode;
  chatgptMode?: ChatGptProviderMode;
  commonCrawlMode?: CommonCrawlProviderMode;
  commonCrawlDomain?: string;
}

/**
 * Builds the POST /api/analyze request body. `urls`/`aiOverviewMode`/
 * `chatgptMode`/`commonCrawlMode`/`commonCrawlDomain` are omitted
 * entirely (not sent as `[]`/`undefined`/`"off"`/empty-string values)
 * rather than included with an empty/default value — the Next.js and
 * Python APIs both treat an omitted key as "use the default", so a
 * normal submission (no urls, no mode selector shown) produces exactly
 * the same body it always has. `commonCrawlMode` follows this same
 * omit-the-default pattern as aiOverviewMode/chatgptMode — omitting
 * "off" is behaviorally identical to sending it explicitly, since the
 * backend already treats an omitted commonCrawlMode as "off" (see
 * backend/main.py).
 */
export function buildAnalyzeRequestBody(
  brandName: string,
  urls: string[],
  aiOverviewMode?: AiOverviewProviderMode,
  chatgptMode?: ChatGptProviderMode,
  commonCrawlMode?: CommonCrawlProviderMode,
  commonCrawlDomain?: string,
): AnalyzeRequestBody {
  const body: AnalyzeRequestBody = { brandName };
  if (urls.length > 0) body.urls = urls;
  if (aiOverviewMode) body.aiOverviewMode = aiOverviewMode;
  if (chatgptMode) body.chatgptMode = chatgptMode;
  if (commonCrawlMode && commonCrawlMode !== "off") body.commonCrawlMode = commonCrawlMode;
  if (commonCrawlDomain && commonCrawlDomain.trim()) {
    body.commonCrawlDomain = commonCrawlDomain.trim();
  }
  return body;
}
