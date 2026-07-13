export type Trend = "up" | "down" | "flat";
export type Sentiment = "positive" | "neutral" | "negative";
export type Priority = "high" | "medium" | "low";

// Whether a given AnalysisResult section was actually computed ("real")
// or is still fixed placeholder data ("mock"). Tracked per section
// because, as of the co-occurrence engine, some sections are real
// while others aren't yet — a single top-level isMock flag can't
// represent that.
export type SectionStatus = "mock" | "real";

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
