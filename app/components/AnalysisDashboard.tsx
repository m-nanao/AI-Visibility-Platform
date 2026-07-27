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
      {/* AI Overview比較はfullSummary/referencesで縦に長くなりやすいため、
          他の短いセクションと同じ1カラム幅ではなくBrandSummarySectionと
          同様に横幅いっぱい（lg:col-span-2）を使う — 狭い2カラムグリッド内
          での折り返し・視認性を改善する（style/widen-ai-overview-section）。 */}
      <div className="lg:col-span-2">
        <AIOverviewComparisonSection items={result.aiOverviewComparison} meta={result.meta} />
      </div>
      <ImprovementSuggestionsSection items={result.improvements} />
    </div>
  );
}
