import { z } from "zod";
import type { AnalysisRunListResponse } from "./analysis-history";

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
