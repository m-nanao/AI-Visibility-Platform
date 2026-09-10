import { z } from "zod";
import type { AnalysisRunDetailResponse, AnalysisRunListResponse } from "./analysis-history";

/**
 * Mirrors backend/models.py's AnalysisRunListItem/AnalysisRunListResponse
 * (GET /analysis-runs). Used to validate responses coming from the
 * Python analysis API before trusting them, same as
 * app/lib/analysis-result-schema.ts does for /analyze.
 *
 * Deliberately has no `result`/`resultJson` field — the list endpoint
 * never returns one (see docs/20_analysis_history_read_api_design.md
 * "5. GET /analysis-runs の設計案"), and this schema doesn't need to
 * know about the detail endpoint's shape at all.
 */

// Pydantic serializes an unset `X | None = None` field as JSON `null`,
// not as an absent key — same reasoning as
// app/lib/analysis-result-schema.ts's optionalFromPython().
function optionalFromPython<T extends z.ZodTypeAny>(schema: T) {
  return schema.nullish().transform((value) => value ?? undefined);
}

const analysisRunListItemSchema = z.object({
  id: z.string(),
  brandName: z.string(),
  canonicalDomain: optionalFromPython(z.string()),
  status: z.string(),
  visibilityScore: optionalFromPython(z.number()),
  sourceSummary: optionalFromPython(z.record(z.string(), z.number())),
  startedAt: optionalFromPython(z.string()),
  completedAt: optionalFromPython(z.string()),
  createdAt: optionalFromPython(z.string()),
});

export const analysisRunListResponseSchema = z.object({
  items: z.array(analysisRunListItemSchema),
  limit: z.number(),
  offset: z.number(),
  total: z.number().nullable(),
});

export type AnalysisRunListParseResult =
  | { success: true; data: AnalysisRunListResponse }
  | { success: false; reason: string };

/**
 * Validates an unknown value (e.g. a parsed JSON body from the Python
 * API) against the AnalysisRunListResponse shape. On failure, `reason`
 * contains only field paths and messages — never the offending values.
 */
export function parseAnalysisRunListResponse(
  input: unknown,
): AnalysisRunListParseResult {
  const result = analysisRunListResponseSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data as AnalysisRunListResponse };
  }

  const reason = result.error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");

  return { success: false, reason };
}

/**
 * Mirrors backend/models.py's AnalysisRunBrand/AnalysisRunInfo/
 * AnalysisRunDetailResponse (GET /analysis-runs/{id}) — see
 * docs/22_analysis_history_detail_ui_design.md "6. 詳細APIとの接続方針".
 *
 * `result` is deliberately validated only as a loose object here, not
 * as the full AnalysisResult shape — a saved row's `result_json` is a
 * point-in-time snapshot that may not match the *current*
 * AnalysisResult schema (see app/lib/analysis-result-schema.ts).
 * Whether it's still compatible is checked separately, by passing this
 * loose `result` through parseAnalysisResult() at the page level (see
 * resolveHistoryDetailFetchOutcome() below) — that's a distinct
 * "incompatible" outcome, not a schema failure of the envelope itself.
 */
const analysisRunBrandSchema = z.object({
  id: z.string(),
  name: z.string(),
  canonicalDomain: optionalFromPython(z.string()),
});

const analysisRunInfoSchema = z.object({
  status: z.string(),
  inputSnapshot: z.record(z.string(), z.unknown()),
  sourceSummary: optionalFromPython(z.record(z.string(), z.number())),
  startedAt: optionalFromPython(z.string()),
  completedAt: optionalFromPython(z.string()),
});

export const analysisRunDetailResponseSchema = z.object({
  id: z.string(),
  brand: analysisRunBrandSchema,
  run: analysisRunInfoSchema,
  result: z.record(z.string(), z.unknown()),
  meta: optionalFromPython(z.record(z.string(), z.unknown())),
});

export type AnalysisRunDetailParseResult =
  | { success: true; data: AnalysisRunDetailResponse }
  | { success: false; reason: string };

/**
 * Validates an unknown value against the AnalysisRunDetailResponse
 * envelope shape (id/brand/run/result/meta) — not against `result`'s
 * inner AnalysisResult shape, see the module doc above.
 */
export function parseAnalysisRunDetailResponse(
  input: unknown,
): AnalysisRunDetailParseResult {
  const result = analysisRunDetailResponseSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data as AnalysisRunDetailResponse };
  }

  const reason = result.error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");

  return { success: false, reason };
}
