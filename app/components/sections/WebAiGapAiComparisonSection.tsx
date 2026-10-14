import Card from "../Card";
import {
  AI_GAP_COMPARISON_PENDING_TEXT,
  getAiGapComparisonButtonLabel,
} from "../../lib/analysis-history";
import type { AiGapActionRecommendation, Priority, WebAiGapAiComparison } from "../../lib/types";

export const AI_COMPARISON_SECTION_TITLE = "AIによる差分比較";
export const AI_COMPARISON_SECTION_DESCRIPTION =
  "保存済みのWeb抜粋とAI観測結果をもとに、意味的な差分をAIが比較した補助的な見立てです。AIの内部認識を直接示すものではありません。";

export const AI_COMPARISON_MATCHED_POINTS_LABEL = "一致している点";
export const AI_COMPARISON_WEB_STRONG_LABEL = "Web上では強いがAI回答では弱い点";
export const AI_COMPARISON_AI_STRONG_LABEL = "AI回答では強いがWeb上では弱い点";
export const AI_COMPARISON_GAP_SUMMARY_LABEL = "ズレの要約";
export const AI_COMPARISON_RECOMMENDATIONS_LABEL = "改善ヒント";

// Shown instead of the structured labels above when
// comparison.method === "ai_comparison_text_fallback" (fix/
// ai-gap-comparison-text-fallback) — Claude returned natural-language
// text with no JSON object in it at all, so there is no structured
// matchedPoints/webStrongAiWeak/aiStrongWebWeak to show.
export const AI_COMPARISON_TEXT_FALLBACK_HEADING = "AIによる差分比較（文章形式）";
export const AI_COMPARISON_TEXT_FALLBACK_NOTE =
  "AIが構造化形式ではなく文章形式で返した比較結果です。保存済みのWeb抜粋とAI観測結果をもとにした補助的な見立てです。";

// Shown for comparison.method === "ai_comparison_json_like_fallback"
// (fix/ai-gap-comparison-json-like-fallback-display) — Claude
// attempted a structured JSON comparison but it didn't fully decode
// (e.g. truncated mid-array); the known fields that could be
// recovered are shown with the same structured layout and the same
// section heading as a normal successful comparison (see the
// "ai_comparison" branch below) — deliberately worded to read like an
// ordinary summary rather than a technical disclaimer, since this is
// shown to 依頼者 (polish/ai-gap-comparison-user-facing-copy) — see
// AI_COMPARISON_SECTION_DESCRIPTION above for the same tone.
export const AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE =
  "保存済みのWeb抜粋とAI観測結果をもとに、AIが比較した内容を整理して表示しています。";

// AI-generated improvement actions (feature/ai-gap-action-
// recommendations), rendered as a distinct section — see
// ActionRecommendationsList below — separate from the rule-based
// `ImprovementSuggestion`s shown elsewhere in the analysis result, and
// from comparison.recommendations above (short one-line hints with no
// evidence/priority/verification). Shown whenever
// comparison.actionRecommendations is a non-empty array, regardless of
// `method` (text-fallback results simply never have any, by design —
// see backend/services/ai_gap_comparison.py).
export const AI_ACTION_RECOMMENDATIONS_HEADING = "AIによる改善提案";
export const AI_ACTION_RECOMMENDATIONS_PRIORITY_LABEL = "優先度";
export const AI_ACTION_RECOMMENDATIONS_ISSUE_LABEL = "課題";
export const AI_ACTION_RECOMMENDATIONS_ACTION_LABEL = "改善方法";
export const AI_ACTION_RECOMMENDATIONS_TARGET_LABEL = "対象箇所";
export const AI_ACTION_RECOMMENDATIONS_EVIDENCE_LABEL = "判断根拠";
export const AI_ACTION_RECOMMENDATIONS_VERIFICATION_LABEL = "再観測での確認方法";

const ACTION_PRIORITY_LABELS: Record<Priority, string> = { high: "高", medium: "中", low: "低" };

export function ActionRecommendationsList({
  recommendations,
}: {
  recommendations?: AiGapActionRecommendation[];
}) {
  if (!recommendations || recommendations.length === 0) return null;
  return (
    <div className="space-y-3 border-t border-zinc-200 pt-3 dark:border-zinc-800">
      <h4 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
        {AI_ACTION_RECOMMENDATIONS_HEADING}
      </h4>
      <ul className="space-y-3">
        {recommendations.map((item, index) => (
          <li
            key={`${index}-${item.title}`}
            className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{item.title}</p>
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                {AI_ACTION_RECOMMENDATIONS_PRIORITY_LABEL}: {ACTION_PRIORITY_LABELS[item.priority]}
              </span>
            </div>
            <dl className="mt-2 space-y-1.5 text-xs text-zinc-600 dark:text-zinc-300">
              <div>
                <dt className="font-medium text-zinc-500 dark:text-zinc-400">
                  {AI_ACTION_RECOMMENDATIONS_ISSUE_LABEL}
                </dt>
                <dd>{item.issue}</dd>
              </div>
              <div>
                <dt className="font-medium text-zinc-500 dark:text-zinc-400">
                  {AI_ACTION_RECOMMENDATIONS_ACTION_LABEL}
                </dt>
                <dd>{item.action}</dd>
              </div>
              <div>
                <dt className="font-medium text-zinc-500 dark:text-zinc-400">
                  {AI_ACTION_RECOMMENDATIONS_TARGET_LABEL}
                </dt>
                <dd>{item.target}</dd>
              </div>
              <div>
                <dt className="font-medium text-zinc-500 dark:text-zinc-400">
                  {AI_ACTION_RECOMMENDATIONS_EVIDENCE_LABEL}
                </dt>
                <dd>{item.evidence}</dd>
              </div>
              <div>
                <dt className="font-medium text-zinc-500 dark:text-zinc-400">
                  {AI_ACTION_RECOMMENDATIONS_VERIFICATION_LABEL}
                </dt>
                <dd>{item.verification}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
    </div>
  );
}

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

        {comparison && comparison.method === "ai_comparison_text_fallback" && (
          <>
            <div>
              <h4 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                {AI_COMPARISON_TEXT_FALLBACK_HEADING}
              </h4>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                {AI_COMPARISON_TEXT_FALLBACK_NOTE}
              </p>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
              {comparison.textSummary || comparison.gapSummary}
            </p>
            <ComparisonList
              label={AI_COMPARISON_RECOMMENDATIONS_LABEL}
              items={comparison.recommendations}
            />
            <ActionRecommendationsList recommendations={comparison.actionRecommendations} />
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{comparison.caution}</p>
          </>
        )}

        {comparison && comparison.method === "ai_comparison_json_like_fallback" && (
          <>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              {AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE}
            </p>
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
            <ActionRecommendationsList recommendations={comparison.actionRecommendations} />
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{comparison.caution}</p>
          </>
        )}

        {comparison && comparison.method === "ai_comparison" && (
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
            <ActionRecommendationsList recommendations={comparison.actionRecommendations} />
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{comparison.caution}</p>
          </>
        )}
      </div>
    </Card>
  );
}
