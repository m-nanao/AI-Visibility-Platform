import { z } from "zod";
import { DOCUMENT_SOURCE_TYPES } from "./document";
import type { AnalysisResult } from "./types";

/**
 * Mirrors app/lib/types.ts's AnalysisResult. Used to validate responses
 * coming from the Python analysis API before trusting them, since that
 * service is a separate process we don't fully control.
 */

const trendSchema = z.enum(["up", "down", "flat"]);
const sentimentSchema = z.enum(["positive", "neutral", "negative"]);
const prioritySchema = z.enum(["high", "medium", "low"]);
const sectionStatusSchema = z.enum(["mock", "real", "unavailable"]);
const documentsSourceSchema = z.enum([
  "development_sample",
  "user_provided",
  "web_fetch",
  "dataforseo",
  "common_crawl",
]);
const documentSourceTypeSchema = z.enum(DOCUMENT_SOURCE_TYPES);

const analysisSectionStatusesSchema = z.object({
  summary: sectionStatusSchema,
  cooccurrenceRanking: sectionStatusSchema,
  contextAnalysis: sectionStatusSchema,
  aiOverviewComparison: sectionStatusSchema,
  improvements: sectionStatusSchema,
});

// Pydantic serializes an unset `X | None = None` field as JSON `null`,
// not as an absent key — so "optional" fields coming from the Python
// API must accept `null` too, not just `undefined`. `.nullish()`
// accepts both, and the `.transform` normalizes null back to
// undefined to match the plain `field?: T` TS type.
function optionalFromPython<T extends z.ZodTypeAny>(schema: T) {
  return schema.nullish().transform((value) => value ?? undefined);
}

const urlFetchResultSchema = z.object({
  url: z.string(),
  success: z.boolean(),
  error: optionalFromPython(z.string()),
});

const analysisMetaSchema = z.object({
  sections: analysisSectionStatusesSchema,
  documentsSource: documentsSourceSchema,
  // offset: true accepts both the "Z" suffix (Date#toISOString(), used by
  // the Next.js dummy data) and "+00:00"-style offsets (Python's
  // datetime.isoformat()).
  generatedAt: z.iso.datetime({ offset: true }),
  urlFetchResults: optionalFromPython(z.array(urlFetchResultSchema)),
  documentCount: optionalFromPython(z.number()),
  sourceTypes: optionalFromPython(z.array(documentSourceTypeSchema)),
});

const brandSummarySchema = z.object({
  brandName: z.string(),
  visibilityScore: z.number(),
  totalMentions: z.number(),
  sentimentBreakdown: z.object({
    positive: z.number(),
    neutral: z.number(),
    negative: z.number(),
  }),
  topPlatforms: z.array(z.string()),
  summaryText: z.string(),
});

const cooccurrenceKeywordSchema = z.object({
  keyword: z.string(),
  count: z.number(),
  trend: trendSchema,
});

const contextAnalysisItemSchema = z.object({
  context: z.string(),
  description: z.string(),
  sentiment: sentimentSchema,
  exampleQuote: z.string(),
});

const aiOverviewComparisonItemSchema = z.object({
  platform: z.string(),
  mentioned: z.boolean(),
  rank: z.number().nullable(),
  summary: z.string(),
});

const improvementSuggestionSchema = z.object({
  title: z.string(),
  description: z.string(),
  priority: prioritySchema,
});

export const analysisResultSchema = z.object({
  brandName: z.string(),
  summary: brandSummarySchema,
  cooccurrenceRanking: z.array(cooccurrenceKeywordSchema),
  contextAnalysis: z.array(contextAnalysisItemSchema),
  aiOverviewComparison: z.array(aiOverviewComparisonItemSchema),
  improvements: z.array(improvementSuggestionSchema),
  meta: analysisMetaSchema,
});

export type AnalysisResultParseResult =
  | { success: true; data: AnalysisResult }
  | { success: false; reason: string };

/**
 * Validates an unknown value (e.g. a parsed JSON body from the Python API)
 * against the AnalysisResult shape. On failure, `reason` contains only
 * field paths and messages — never the offending values — so callers can
 * log it safely.
 */
export function parseAnalysisResult(input: unknown): AnalysisResultParseResult {
  const result = analysisResultSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data as AnalysisResult };
  }

  const reason = result.error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");

  return { success: false, reason };
}
