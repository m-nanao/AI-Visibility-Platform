import type { DocumentSourceType } from "./document";

export type Trend = "up" | "down" | "flat";
export type Sentiment = "positive" | "neutral" | "negative";
export type Priority = "high" | "medium" | "low";

// Whether a given AnalysisResult section was actually computed
// ("real"), is still fixed placeholder data ("mock"), or couldn't be
// computed because its input couldn't be obtained ("unavailable" —
// e.g. every url in `urls` failed to fetch). Tracked per section
// because, as of the co-occurrence engine, some sections are real
// while others aren't yet — a single top-level isMock flag can't
// represent that. "unavailable" is distinct from a "real" section
// that legitimately computed zero results.
export type SectionStatus = "mock" | "real" | "unavailable";

export interface AnalysisSectionStatuses {
  summary: SectionStatus;
  cooccurrenceRanking: SectionStatus;
  contextAnalysis: SectionStatus;
  aiOverviewComparison: SectionStatus;
  improvements: SectionStatus;
}

// Where the text corpus fed into the (co-occurrence) analysis came
// from. dataforseo/common_crawl are reserved for future data sources.
export type DocumentsSource =
  | "development_sample"
  | "user_provided"
  | "web_fetch"
  | "dataforseo"
  | "common_crawl";

export interface UrlFetchResult {
  url: string;
  success: boolean;
  error?: string;
}

export interface AnalysisMeta {
  sections: AnalysisSectionStatuses;
  documentsSource: DocumentsSource;
  generatedAt: string;
  // Present only when documentsSource is "web_fetch".
  urlFetchResults?: UrlFetchResult[];
  // Summary of the Document[] actually processed server-side (see
  // app/lib/document.ts) — undefined when documentsSource is
  // "development_sample", which isn't wrapped as Document[] yet. The
  // Document[] itself is never sent to the client in bulk.
  documentCount?: number;
  sourceTypes?: DocumentSourceType[];
}

export interface BrandSummary {
  brandName: string;
  visibilityScore: number;
  totalMentions: number;
  sentimentBreakdown: {
    positive: number;
    neutral: number;
    negative: number;
  };
  topPlatforms: string[];
  summaryText: string;
}

export interface CooccurrenceKeyword {
  keyword: string;
  count: number;
  trend: Trend;
}

export interface ContextAnalysisItem {
  context: string;
  description: string;
  sentiment: Sentiment;
  exampleQuote: string;
}

export interface AIOverviewComparisonItem {
  platform: string;
  mentioned: boolean;
  rank: number | null;
  summary: string;
}

export interface ImprovementSuggestion {
  title: string;
  description: string;
  priority: Priority;
}

export interface AnalysisResult {
  brandName: string;
  summary: BrandSummary;
  cooccurrenceRanking: CooccurrenceKeyword[];
  contextAnalysis: ContextAnalysisItem[];
  aiOverviewComparison: AIOverviewComparisonItem[];
  improvements: ImprovementSuggestion[];
  meta: AnalysisMeta;
}
