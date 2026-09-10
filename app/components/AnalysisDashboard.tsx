import Link from "next/link";
import type { AnalysisResult } from "../lib/types";
import {
  POST_ANALYZE_HISTORY_LINK_HELPER_TEXT,
  POST_ANALYZE_HISTORY_LINK_TEXT,
  resolvePostAnalyzeHistoryLink,
} from "../lib/analysis-history";
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
  // Only rendered when result.analysisRunId is a saved analysis_runs.id
  // (DB save succeeded) — see
  // docs/23_analysis_run_id_and_post_analyze_link_design.md "8. 分析結果
  // 画面のリンク表示方針". READ_HISTORY_ENABLED=false is deliberately
  // not checked here; the linked /history/[id] page shows its own
  // disabled message in that case.
  const historyLink = resolvePostAnalyzeHistoryLink(result.analysisRunId);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {historyLink && (
        <div className="lg:col-span-2 flex flex-wrap items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
          <span>{POST_ANALYZE_HISTORY_LINK_HELPER_TEXT}</span>
          <Link
            href={historyLink.path}
            className="text-zinc-700 underline-offset-2 hover:underline dark:text-zinc-300"
          >
            {POST_ANALYZE_HISTORY_LINK_TEXT}
          </Link>
        </div>
      )}
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
