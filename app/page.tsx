"use client";

import { useState } from "react";
import Link from "next/link";
import AppHeader from "./components/AppHeader";
import BrandInputForm from "./components/BrandInputForm";
import AnalysisDashboard from "./components/AnalysisDashboard";
import {
  ANALYZE_FALLBACK_HEADER,
  ANALYZE_FALLBACK_REASON_HEADER,
  buildAnalyzeRequestBody,
  getAnalyzeFallbackMessage,
} from "./lib/analysis-request";
import {
  ANALYSIS_RESULT_PREVIEW_NOTE,
  HISTORY_LIST_LINK_TEXT,
  HISTORY_LIST_PATH,
  POST_ANALYZE_HISTORY_CARD_HEADING,
  POST_ANALYZE_HISTORY_LINK_HELPER_TEXT,
  POST_ANALYZE_HISTORY_LINK_TEXT,
  resolvePostAnalyzeHistoryLink,
} from "./lib/analysis-history";
import { getSectionStatusSummary } from "./lib/meta-label";
import { STAGING_BANNER_TEXT } from "./lib/staging-banner";
import type {
  AiOverviewProviderMode,
  AnalysisResult,
  ChatGptProviderMode,
  ClaudeProviderMode,
  CommonCrawlProviderMode,
  GeminiProviderMode,
} from "./lib/types";

type Status = "idle" | "loading" | "done" | "error";

export default function Home() {
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Whether the in-flight (or most recently finished) request included
  // urls, so the loading message can say "fetching web pages" instead
  // of the generic message — url-based analysis can take much longer.
  const [isUrlAnalysis, setIsUrlAnalysis] = useState(false);
  // Set from ANALYZE_FALLBACK_HEADER/ANALYZE_FALLBACK_REASON_HEADER
  // (app/lib/analysis-request.ts) when /api/analyze had to fall back to
  // dummy data — see that file's comment for why this can legitimately
  // happen even though the Python API ends up completing and saving a
  // real result (full-ON requests taking longer than this route is
  // willing to wait). null on a real result.
  const [fallbackMessage, setFallbackMessage] = useState<string | null>(null);

  const handleAnalyze = async (
    brandName: string,
    urls: string[],
    aiOverviewMode?: AiOverviewProviderMode,
    chatgptMode?: ChatGptProviderMode,
    commonCrawlMode?: CommonCrawlProviderMode,
    commonCrawlDomain?: string,
    claudeMode?: ClaudeProviderMode,
    geminiMode?: GeminiProviderMode,
  ) => {
    setStatus("loading");
    setError(null);
    setFallbackMessage(null);
    setIsUrlAnalysis(urls.length > 0);
    try {
      // urls: [] is never sent — omitting the key entirely lets the
      // API fall back to its own default (development sample
      // documents), and keeps `urls: []` reserved as an explicit
      // "reject this request" signal on the API side. aiOverviewMode/
      // chatgptMode/commonCrawlMode/commonCrawlDomain/claudeMode/
      // geminiMode are only present when BrandInputForm's
      // dev/verification-only mode selectors are shown (see
      // app/lib/analysis-request.ts) — otherwise they're undefined and
      // omitted here too, same as before.
      const requestBody = buildAnalyzeRequestBody(
        brandName,
        urls,
        aiOverviewMode,
        chatgptMode,
        commonCrawlMode,
        commonCrawlDomain,
        claudeMode,
        geminiMode,
      );

      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null);
        throw new Error(errorBody?.error ?? "分析に失敗しました。");
      }

      if (response.headers.get(ANALYZE_FALLBACK_HEADER)) {
        setFallbackMessage(
          getAnalyzeFallbackMessage(response.headers.get(ANALYZE_FALLBACK_REASON_HEADER)),
        );
      }

      const data: AnalysisResult = await response.json();
      setResult(data);
      setStatus("done");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "分析中にエラーが発生しました。",
      );
      setStatus("error");
    }
  };


  const handleReset = () => {
    setStatus("idle");
    setResult(null);
    setError(null);
    setFallbackMessage(null);
    setIsUrlAnalysis(false);
  };

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <AppHeader />
      <div className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Web上の情報環境をもとに、ブランドがAI上でどのように扱われやすいかを推定します
          </p>
          <p className="mt-2 inline-block rounded bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            {STAGING_BANNER_TEXT}
          </p>
        </div>
      </div>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <BrandInputForm
            onSubmit={handleAnalyze}
            isLoading={status === "loading"}
            initialValue={result?.brandName ?? ""}
          />
        </div>

        {error && (
          <p className="mt-4 text-sm text-rose-600 dark:text-rose-400">
            {error}
          </p>
        )}

        {status === "loading" && (
          <p className="mt-8 text-sm text-zinc-500 dark:text-zinc-400">
            {isUrlAnalysis
              ? "Webページを取得・分析しています。20〜25秒ほどかかる場合があります..."
              : "分析中です。しばらくお待ちください..."}
          </p>
        )}

        {status === "done" && result && (
          <div className="mt-8">
            {/* Prominent callout — only when the result was actually
                saved (result.analysisRunId set). Placed above
                everything else in the result area, per
                improve/history-centered-analysis-flow's "分析結果の
                上部、できれば目立つカード形式" — the analysis result
                screen is a preview; the history detail screen is
                where the saved result/report/Gemini rerun actually
                live. */}
            {(() => {
              const historyLink = resolvePostAnalyzeHistoryLink(result.analysisRunId);
              if (!historyLink) return null;
              return (
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950">
                  <div>
                    <p className="text-sm font-medium text-blue-900 dark:text-blue-200">
                      {POST_ANALYZE_HISTORY_CARD_HEADING}
                    </p>
                    <p className="mt-0.5 text-xs text-blue-800 dark:text-blue-300">
                      {POST_ANALYZE_HISTORY_LINK_HELPER_TEXT}
                    </p>
                  </div>
                  <Link
                    href={historyLink.path}
                    className="shrink-0 rounded bg-blue-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-800 dark:bg-blue-600 dark:hover:bg-blue-500"
                  >
                    {POST_ANALYZE_HISTORY_LINK_TEXT}
                  </Link>
                </div>
              );
            })()}

            {/* Always shown while a result is displayed, kept
                deliberately short/muted so it doesn't compete with the
                result content itself on a normal run. */}
            <p className="mb-3 text-xs text-zinc-400 dark:text-zinc-500">
              {ANALYSIS_RESULT_PREVIEW_NOTE}
            </p>

            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h2 className="text-sm text-zinc-500 dark:text-zinc-400">
                  「{result.brandName}」の分析結果
                </h2>
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                  {getSectionStatusSummary(result.meta)}
                </span>
              </div>
              <button
                type="button"
                onClick={handleReset}
                className="text-sm text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
              >
                リセット
              </button>
            </div>
            {fallbackMessage && (
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                <p>{fallbackMessage}</p>
                <Link
                  href={HISTORY_LIST_PATH}
                  className="shrink-0 text-xs font-medium underline-offset-2 hover:underline"
                >
                  {HISTORY_LIST_LINK_TEXT}
                </Link>
              </div>
            )}
            <AnalysisDashboard result={result} />
          </div>
        )}
      </main>
    </div>
  );
}
