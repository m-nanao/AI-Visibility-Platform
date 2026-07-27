import type { AiOverviewProviderMode } from "./types";

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

export interface AnalyzeRequestBody {
  brandName: string;
  urls?: string[];
  aiOverviewMode?: AiOverviewProviderMode;
}

/**
 * Builds the POST /api/analyze request body. `urls`/`aiOverviewMode`
 * are omitted entirely (not sent as `[]`/`undefined` values) rather
 * than included with an empty/default value — the Next.js and Python
 * APIs both treat an omitted key as "use the default", so a normal
 * submission (no urls, mode selector not shown) produces exactly the
 * same body it always has.
 */
export function buildAnalyzeRequestBody(
  brandName: string,
  urls: string[],
  aiOverviewMode?: AiOverviewProviderMode,
): AnalyzeRequestBody {
  const body: AnalyzeRequestBody = { brandName };
  if (urls.length > 0) body.urls = urls;
  if (aiOverviewMode) body.aiOverviewMode = aiOverviewMode;
  return body;
}
