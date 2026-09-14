// Static explanatory copy for the MVP review pass — helps a 依頼者
// (non-engineer reviewer) understand what the analysis screens are
// actually showing: the distinction between the Web上の情報環境
// ("原因側") that feeds the analysis and the AI Overview/ChatGPT
// observations ("結果側") it's compared against, and how to read the
// gap between the two as an improvement hint.
//
// Deliberately separate from app/lib/meta-label.ts: everything in this
// file is fixed text with no dependency on AnalysisResult/AnalysisMeta
// (nothing here is computed from a specific analysis run), whereas
// meta-label.ts derives its display values from the result/meta of one
// specific request. Reused verbatim across the analysis result screen,
// the history detail screen (both via AnalysisGuideCard, since both
// render AnalysisDashboard), and the report page (which has its own
// layout and imports these constants directly).

export const ANALYSIS_GUIDE_TITLE = "この分析の見方";

export const ANALYSIS_GUIDE_INTRO =
  "この分析では、Web上の情報環境（原因側）と、AI Overview / ChatGPT観測（結果側）を分けて確認します。";

export const ANALYSIS_GUIDE_OUTRO =
  "両方を見ることで、Web上の説明がAI回答にどう反映されやすいかを改善するためのヒントを得ます。";

export interface AnalysisGuideSection {
  label: string;
  text: string;
  items?: string[];
}

export const WEB_ENVIRONMENT_GUIDE: AnalysisGuideSection = {
  label: "原因側: Web情報環境",
  text: "入力URL・Common Crawl由来の情報から、ブランドがどの文脈で説明されているかを確認します。",
  items: ["入力URL", "Common Crawl補完", "共起語", "文脈分析", "Web上のブランド説明"],
};

export const AI_OBSERVATION_GUIDE: AnalysisGuideSection = {
  label: "結果側: AI観測",
  text: "AI OverviewやChatGPT相当モデルで、ブランドがどのように回答されるかを確認します。",
  items: [
    "Google AI Overview / AI Mode上の回答・参照状況",
    "ChatGPT相当モデルでの回答傾向",
  ],
};

export const IMPROVEMENT_HINT_GUIDE: AnalysisGuideSection = {
  label: "改善ヒント",
  text: "Web上の説明とAI回答にズレがある場合、公式ページの見出し・本文・FAQ・事例を改善する候補になります。",
};
