import type { AnalysisResult } from "../lib/types";
import BrandSummarySection from "./sections/BrandSummarySection";
import CooccurrenceRankingSection from "./sections/CooccurrenceRankingSection";
import ContextAnalysisSection from "./sections/ContextAnalysisSection";
import AIOverviewComparisonSection from "./sections/AIOverviewComparisonSection";
import ImprovementSuggestionsSection from "./sections/ImprovementSuggestionsSection";

export default function AnalysisDashboard({
  result,
}: {
  result: AnalysisResult;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="lg:col-span-2">
        <BrandSummarySection summary={result.summary} />
      </div>
      <CooccurrenceRankingSection items={result.cooccurrenceRanking} meta={result.meta} />
      <ContextAnalysisSection items={result.contextAnalysis} />
      <AIOverviewComparisonSection items={result.aiOverviewComparison} meta={result.meta} />
      <ImprovementSuggestionsSection items={result.improvements} />
    </div>
  );
}
