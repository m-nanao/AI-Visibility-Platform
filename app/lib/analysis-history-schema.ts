import { z } from "zod";
import type {
  AnalysisRunComparisonResponse,
  AnalysisRunDetailResponse,
  AnalysisRunListResponse,
} from "./analysis-history";

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

/**
 * Mirrors backend/models.py's AnalysisRunComparison* models (GET
 * /analysis-runs/{id}/comparison) — see
 * docs/25_analysis_history_comparison_design.md "8. API設計案". Unlike
 * the list/detail schemas above, `startedAt`/`visibilityScore` here
 * use plain `.nullable()` rather than optionalFromPython(): the key is
 * always present on this response, and `null` is a meaningful value
 * (e.g. "no earlier run" for `previous`), not merely Pydantic's
 * unset-optional-field serialization quirk.
 */
const analysisRunComparisonRunSummarySchema = z.object({
  id: z.string(),
  startedAt: z.string().nullable(),
  visibilityScore: z.number().nullable(),
});

const analysisRunComparisonVisibilityScoreDiffSchema = z.object({
  current: z.number().nullable(),
  previous: z.number().nullable(),
  delta: z.number().nullable(),
});

const cooccurrenceComparisonNewTermSchema = z.object({
  term: z.string(),
  rank: z.number(),
  score: z.number(),
});

const cooccurrenceComparisonRemovedTermSchema = z.object({
  term: z.string(),
  rank: z.number(),
  score: z.number(),
});

const cooccurrenceComparisonChangedTermSchema = z.object({
  term: z.string(),
  currentRank: z.number(),
  previousRank: z.number(),
  rankDelta: z.number(),
  currentScore: z.number(),
  previousScore: z.number(),
  scoreDelta: z.number(),
});

const analysisRunComparisonCooccurrenceDiffSchema = z.object({
  topN: z.number(),
  newTerms: z.array(cooccurrenceComparisonNewTermSchema),
  removedTerms: z.array(cooccurrenceComparisonRemovedTermSchema),
  changedTerms: z.array(cooccurrenceComparisonChangedTermSchema),
});

const analysisRunComparisonImprovementsDiffSchema = z.object({
  currentCount: z.number(),
  previousCount: z.number(),
  delta: z.number(),
});

const analysisRunComparisonDiffSchema = z.object({
  visibilityScore: analysisRunComparisonVisibilityScoreDiffSchema,
  cooccurrence: analysisRunComparisonCooccurrenceDiffSchema,
  improvements: analysisRunComparisonImprovementsDiffSchema,
});

export const analysisRunComparisonResponseSchema = z.object({
  current: analysisRunComparisonRunSummarySchema,
  previous: analysisRunComparisonRunSummarySchema.nullable(),
  diff: analysisRunComparisonDiffSchema.nullable(),
  warnings: z.array(z.string()),
});

export type AnalysisRunComparisonParseResult =
  | { success: true; data: AnalysisRunComparisonResponse }
  | { success: false; reason: string };

/**
 * Validates an unknown value against the AnalysisRunComparisonResponse
 * shape. On failure, `reason` contains only field paths and messages —
 * never the offending values.
 */
export function parseAnalysisRunComparisonResponse(
  input: unknown,
): AnalysisRunComparisonParseResult {
  const result = analysisRunComparisonResponseSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data as AnalysisRunComparisonResponse };
  }

  const reason = result.error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");

  return { success: false, reason };
}
