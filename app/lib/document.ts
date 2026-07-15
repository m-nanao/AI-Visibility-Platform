// Distinct from AnalysisMeta.documentsSource (types.ts): documentsSource
// summarizes the whole AnalysisResult response, while a Document's
// sourceType tags one unit of analyzable text at a time. The two may be
// unified later — see docs/11_architecture_v1.md "4. Document Pipeline".
export const DOCUMENT_SOURCE_TYPES = [
  "user_provided",
  "web_fetch",
  "development_sample",
  "common_crawl",
  "dataforseo",
] as const;

export type DocumentSourceType = (typeof DOCUMENT_SOURCE_TYPES)[number];

/**
 * A single unit of analyzable text, normalized across data sources.
 * See docs/11_architecture_v1.md "4. Document Pipeline" — every data
 * source (user-provided text, URL fetch today; Common Crawl,
 * DataForSEO tomorrow) is meant to become Document[] before reaching
 * the Analyzer, so adding a new source never means teaching the
 * analyzer about it.
 *
 * This is internal/backend-side processing shape, not something the
 * frontend currently receives in bulk — AnalysisResult only exposes a
 * summary of it (meta.documentCount / meta.sourceTypes in types.ts).
 */
export interface Document {
  id: string;
  sourceType: DocumentSourceType;
  sourceUrl?: string;
  title?: string;
  domain?: string;
  fetchedAt: string; // ISO 8601
  text: string;
  metadata?: Record<string, unknown>;
}
