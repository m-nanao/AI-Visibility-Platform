import type { AiOverviewProviderMode, ChatGptProviderMode } from "./types";

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

export interface AnalyzeRequestBody {
  brandName: string;
  urls?: string[];
  aiOverviewMode?: AiOverviewProviderMode;
  chatgptMode?: ChatGptProviderMode;
}

/**
 * Builds the POST /api/analyze request body. `urls`/`aiOverviewMode`/
 * `chatgptMode` are omitted entirely (not sent as `[]`/`undefined`
 * values) rather than included with an empty/default value — the
 * Next.js and Python APIs both treat an omitted key as "use the
 * default", so a normal submission (no urls, neither mode selector
 * shown) produces exactly the same body it always has.
 */
export function buildAnalyzeRequestBody(
  brandName: string,
  urls: string[],
  aiOverviewMode?: AiOverviewProviderMode,
  chatgptMode?: ChatGptProviderMode,
): AnalyzeRequestBody {
  const body: AnalyzeRequestBody = { brandName };
  if (urls.length > 0) body.urls = urls;
  if (aiOverviewMode) body.aiOverviewMode = aiOverviewMode;
  if (chatgptMode) body.chatgptMode = chatgptMode;
  return body;
}
