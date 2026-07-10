import type { AnalysisMeta, AnalysisSource } from "./types";

const SOURCE_LABELS: Record<AnalysisSource, string> = {
  python_mock: "Python API",
  nextjs_mock: "Next.jsフォールバック",
  real_analysis: "Python API",
};

export function getSourceLabel(meta: AnalysisMeta): string {
  const base = SOURCE_LABELS[meta.source];
  return meta.isMock ? `${base}（ダミー）` : base;
}
