import { z } from "zod";
import type { AnalysisResult } from "./types";

/**
 * Mirrors app/lib/types.ts's AnalysisResult. Used to validate responses
 * coming from the Python analysis API before trusting them, since that
 * service is a separate process we don't fully control.
 */

const trendSchema = z.enum(["up", "down", "flat"]);
const sentimentSchema = z.enum(["positive", "neutral", "negative"]);
const prioritySchema = z.enum(["high", "medium", "low"]);
const analysisSourceSchema = z.enum([
  "python_mock",
  "nextjs_mock",
  "real_analysis",
]);

const analysisMetaSchema = z.object({
  source: analysisSourceSchema,
  isMock: z.boolean(),
  generatedAt: z.string(),
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
