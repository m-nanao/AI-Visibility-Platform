export type Trend = "up" | "down" | "flat";
export type Sentiment = "positive" | "neutral" | "negative";
export type Priority = "high" | "medium" | "low";
export type AnalysisSource = "python_mock" | "nextjs_mock" | "real_analysis";

export interface AnalysisMeta {
  source: AnalysisSource;
  isMock: boolean;
  generatedAt: string;
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
