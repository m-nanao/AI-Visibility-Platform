import { z } from "zod";

/**
 * Mirrors backend/models.py's AnalysisJobAcceptedResponse /
 * AnalysisJobStatusResponse / AnalysisJobResultResponse / MeProjectsResponse
 * (POST /analysis-jobs, GET /analysis-jobs/{id}, GET
 * /analysis-jobs/{id}/result, GET /me/projects) — same "validate before
 * trusting" discipline as app/lib/analysis-history-schema.ts and
 * app/lib/analysis-result-schema.ts.
 */

// Pydantic serializes an unset `X | None = None` field as JSON `null`,
// not as an absent key — same reasoning as
// app/lib/analysis-result-schema.ts's optionalFromPython() and
// app/lib/analysis-history-schema.ts's copy of it.
function optionalFromPython<T extends z.ZodTypeAny>(schema: T) {
  return schema.nullish().transform((value) => value ?? undefined);
}

export const analysisJobAcceptedResponseSchema = z.object({
  analysisRunId: z.string(),
  status: z.string(),
});

export const analysisJobStatusResponseSchema = z.object({
  analysisRunId: z.string(),
  status: z.string(),
  startedAt: optionalFromPython(z.string()),
  completedAt: optionalFromPython(z.string()),
  errorMessage: optionalFromPython(z.string()),
});

export const analysisJobResultResponseSchema = z.object({
  analysisRunId: z.string(),
  status: z.string(),
  errorMessage: optionalFromPython(z.string()),
  // Kept as loose records (not `AnalysisResult`) — same reasoning as
  // AnalysisRunDetailResponse's `result` field in
  // app/lib/analysis-history.ts: validated separately by
  // app/lib/analysis-result-schema.ts's parseAnalysisResult() once
  // this envelope itself is confirmed valid.
  result: optionalFromPython(z.record(z.string(), z.unknown())),
  meta: optionalFromPython(z.record(z.string(), z.unknown())),
});

export const meProjectsResponseSchema = z.object({
  projects: z.array(z.object({ id: z.string() })),
});

export type AnalysisJobAcceptedResponseParsed = z.infer<typeof analysisJobAcceptedResponseSchema>;
export type AnalysisJobStatusResponseParsed = z.infer<typeof analysisJobStatusResponseSchema>;
export type AnalysisJobResultResponseParsed = z.infer<typeof analysisJobResultResponseSchema>;
export type MeProjectsResponseParsed = z.infer<typeof meProjectsResponseSchema>;

type ParseResult<T> = { success: true; data: T } | { success: false; reason: string };

function parseWith<T>(
  schema: z.ZodType<T>,
  input: unknown,
): ParseResult<T> {
  const result = schema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data };
  }
  const reason = result.error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");
  return { success: false, reason };
}

export function parseAnalysisJobAcceptedResponse(
  input: unknown,
): ParseResult<AnalysisJobAcceptedResponseParsed> {
  return parseWith(analysisJobAcceptedResponseSchema, input);
}

export function parseAnalysisJobStatusResponse(
  input: unknown,
): ParseResult<AnalysisJobStatusResponseParsed> {
  return parseWith(analysisJobStatusResponseSchema, input);
}

export function parseAnalysisJobResultResponse(
  input: unknown,
): ParseResult<AnalysisJobResultResponseParsed> {
  return parseWith(analysisJobResultResponseSchema, input);
}

export function parseMeProjectsResponse(input: unknown): ParseResult<MeProjectsResponseParsed> {
  return parseWith(meProjectsResponseSchema, input);
}
