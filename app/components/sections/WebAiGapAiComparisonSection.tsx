import Card from "../Card";
import {
  AI_GAP_COMPARISON_PENDING_TEXT,
  getAiGapComparisonButtonLabel,
} from "../../lib/analysis-history";
import type { WebAiGapAiComparison } from "../../lib/types";

export const AI_COMPARISON_SECTION_TITLE = "AIによる差分比較";
export const AI_COMPARISON_SECTION_DESCRIPTION =
  "保存済みのWeb抜粋とAI観測結果をもとに、意味的な差分をAIが比較した補助的な見立てです。AIの内部認識を直接示すものではありません。";

export const AI_COMPARISON_MATCHED_POINTS_LABEL = "一致している点";
export const AI_COMPARISON_WEB_STRONG_LABEL = "Web上では強いがAI回答では弱い点";
export const AI_COMPARISON_AI_STRONG_LABEL = "AI回答では強いがWeb上では弱い点";
export const AI_COMPARISON_GAP_SUMMARY_LABEL = "ズレの要約";
export const AI_COMPARISON_RECOMMENDATIONS_LABEL = "改善ヒント";

// Passed only by the history detail page (app/history/[id]/page.tsx) —
// mirrors AIOverviewComparisonSection.tsx's GeminiRerunControlsState
// pattern. The analysis result screen never passes this (no generate
// button there, see feature/manual-ai-gap-comparison's "重要方針":
// 通常分析には組み込まない), and the report page never passes this
// either (comparison-display only, no generate button on that
// screen). `onGenerate` is expected to show its own window.confirm()
// before doing anything (see AI_GAP_COMPARISON_CONFIRM_MESSAGE in
// app/lib/analysis-history.ts) — this component only renders the
// button/description/in-flight-state, it never confirms on its own.
export type AiGapComparisonControlsState = {
  status: "idle" | "pending";
  errorMessage?: string;
  successMessage?: string;
  onGenerate: () => void;
};

function ComparisonList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">{label}</h4>
      <ul className="mt-1 list-inside list-disc space-y-1 text-sm text-zinc-700 dark:text-zinc-300">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

// Independent of WebAiGapSection.tsx (the existing rule-based
// comparison) — rendered as its own Card right after it, never
// replacing it. Renders nothing at all when there is neither a
// generated `comparison` nor a `controls` (generate button) to show —
// which is always the case on the analysis result screen, since
// `controls` is only ever passed by the history detail page and
// `comparison` is never populated by a normal `/analyze` request.
export default function WebAiGapAiComparisonSection({
  comparison,
  controls,
}: {
  comparison?: WebAiGapAiComparison;
  controls?: AiGapComparisonControlsState;
}) {
  if (!comparison && !controls) return null;

  return (
    <Card title={AI_COMPARISON_SECTION_TITLE} description={AI_COMPARISON_SECTION_DESCRIPTION}>
      <div className="space-y-4">
        {controls && (
          <div className="print:hidden">
            <button
              type="button"
              onClick={controls.onGenerate}
              disabled={controls.status === "pending"}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              {controls.status === "pending"
                ? AI_GAP_COMPARISON_PENDING_TEXT
                : getAiGapComparisonButtonLabel(Boolean(comparison))}
            </button>
            {controls.errorMessage && (
              <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                {controls.errorMessage}
              </p>
            )}
            {controls.successMessage && (
              <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
                {controls.successMessage}
              </p>
            )}
          </div>
        )}

        {comparison && (
          <>
            <ComparisonList
              label={AI_COMPARISON_MATCHED_POINTS_LABEL}
              items={comparison.matchedPoints}
            />
            <ComparisonList
              label={AI_COMPARISON_WEB_STRONG_LABEL}
              items={comparison.webStrongAiWeak}
            />
            <ComparisonList
              label={AI_COMPARISON_AI_STRONG_LABEL}
              items={comparison.aiStrongWebWeak}
            />
            {comparison.gapSummary && (
              <div>
                <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                  {AI_COMPARISON_GAP_SUMMARY_LABEL}
                </h4>
                <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
                  {comparison.gapSummary}
                </p>
              </div>
            )}
            <ComparisonList
              label={AI_COMPARISON_RECOMMENDATIONS_LABEL}
              items={comparison.recommendations}
            />
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{comparison.caution}</p>
          </>
        )}
      </div>
    </Card>
  );
}
