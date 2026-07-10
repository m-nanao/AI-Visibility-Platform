"use client";

import { useState } from "react";
import BrandInputForm from "./components/BrandInputForm";
import AnalysisDashboard from "./components/AnalysisDashboard";
import type { AnalysisResult } from "./lib/types";

type Status = "idle" | "loading" | "done" | "error";

export default function Home() {
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async (brandName: string) => {
    setStatus("loading");
    setError(null);
    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brandName }),
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null);
        throw new Error(errorBody?.error ?? "分析に失敗しました。");
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
  };

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            LLMO / AI Visibility Platform
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            ブランドがAIサービス上でどのように認知されているかを分析します
          </p>
        </div>
      </header>

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
            分析中です。しばらくお待ちください...
          </p>
        )}

        {status === "done" && result && (
          <div className="mt-8">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm text-zinc-500 dark:text-zinc-400">
                「{result.brandName}」の分析結果（ダミーデータ）
              </h2>
              <button
                type="button"
                onClick={handleReset}
                className="text-sm text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
              >
                リセット
              </button>
            </div>
            <AnalysisDashboard result={result} />
          </div>
        )}
      </main>
    </div>
  );
}
