"use client";

import { useState, type FormEvent } from "react";
import {
  isAiOverviewModeSelectorEnabled,
  isChatGptModeSelectorEnabled,
} from "../lib/analysis-request";
import { MAX_URLS, validateUrlsInput } from "../lib/url-validation";
import type { AiOverviewProviderMode, ChatGptProviderMode } from "../lib/types";

const AI_OVERVIEW_MODE_OPTIONS: { value: AiOverviewProviderMode; label: string }[] = [
  { value: "mock", label: "モック" },
  { value: "off", label: "オフ" },
  { value: "dataforseo_sandbox", label: "DataForSEO Sandbox" },
  { value: "dataforseo_live", label: "DataForSEO Live" },
  { value: "dataforseo", label: "dataforseo: DataForSEO（env依存・非推奨）" },
];

const CHATGPT_MODE_OPTIONS: { value: ChatGptProviderMode; label: string }[] = [
  { value: "off", label: "off: 無効" },
  { value: "openai", label: "openai: OpenAI API" },
];

export default function BrandInputForm({
  onSubmit,
  isLoading,
  initialValue = "",
}: {
  onSubmit: (
    brandName: string,
    urls: string[],
    aiOverviewMode?: AiOverviewProviderMode,
    chatgptMode?: ChatGptProviderMode,
  ) => void;
  isLoading: boolean;
  initialValue?: string;
}) {
  const [brandName, setBrandName] = useState(initialValue);
  const [urlsInput, setUrlsInput] = useState("");
  const [urlErrors, setUrlErrors] = useState<string[]>([]);
  const [aiOverviewMode, setAiOverviewMode] = useState<AiOverviewProviderMode>("mock");
  const [chatgptMode, setChatgptMode] = useState<ChatGptProviderMode>("off");
  const showAiOverviewModeSelector = isAiOverviewModeSelectorEnabled();
  const showChatGptModeSelector = isChatGptModeSelectorEnabled();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Extra guard against double submission beyond the disabled button
    // (e.g. a keyboard-triggered submit racing with an in-flight request).
    if (isLoading) return;

    const trimmedBrandName = brandName.trim();
    if (!trimmedBrandName) return;

    const { urls, errors } = validateUrlsInput(urlsInput);
    if (errors.length > 0) {
      setUrlErrors(errors);
      return;
    }

    setUrlErrors([]);
    // aiOverviewMode/chatgptMode are only ever passed when their
    // respective dev/verification-only selectors are actually shown —
    // otherwise this behaves exactly as before (undefined), so a
    // normal submission's request body is unaffected by either
    // selector's existence.
    onSubmit(
      trimmedBrandName,
      urls,
      showAiOverviewModeSelector ? aiOverviewMode : undefined,
      showChatGptModeSelector ? chatgptMode : undefined,
    );
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label
            htmlFor="brandName"
            className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300"
          >
            ブランド名
          </label>
          <input
            id="brandName"
            name="brandName"
            type="text"
            required
            disabled={isLoading}
            value={brandName}
            onChange={(event) => setBrandName(event.target.value)}
            placeholder="例: サンプル株式会社"
            className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          />
        </div>
        <button
          type="submit"
          disabled={isLoading || !brandName.trim()}
          className="inline-flex h-10 items-center justify-center rounded-md bg-zinc-900 px-5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {isLoading ? "分析中..." : "分析開始"}
        </button>
      </div>

      <div>
        <label
          htmlFor="urls"
          className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300"
        >
          分析対象URL（任意・1行に1件・最大{MAX_URLS}件）
        </label>
        <textarea
          id="urls"
          name="urls"
          rows={4}
          disabled={isLoading}
          value={urlsInput}
          onChange={(event) => {
            setUrlsInput(event.target.value);
            if (urlErrors.length > 0) setUrlErrors([]);
          }}
          placeholder={"https://example.com/article-a\nhttps://example.com/article-b"}
          className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-xs text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
        />
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          未入力の場合は開発用のサンプル文章で分析します。URLを指定した場合、Webページの取得・分析に20〜25秒ほどかかることがあります。
        </p>
        {urlErrors.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-950 dark:text-rose-400">
            {urlErrors.map((message, index) => (
              <li key={index}>{message}</li>
            ))}
          </ul>
        )}
      </div>

      {/* Dev/verification-only — see app/lib/analysis-request.ts's
          isAiOverviewModeSelectorEnabled(). Selecting "dataforseo_live"
          (or "dataforseo" with the right env) here only sends
          aiOverviewMode in the request body; whether the Python API
          actually honors it (and, separately, whether it reaches
          DataForSEO Live) still depends entirely on server-side gates
          that this UI cannot change. "dataforseo_sandbox"/"dataforseo_live"
          are explicit about which host they mean; plain "dataforseo" is
          kept only for backwards compatibility (its Sandbox-vs-Live
          choice still depends on the backend's DATAFORSEO_API_ENV). */}
      {showAiOverviewModeSelector && (
        <div className="rounded-md border border-dashed border-amber-300 bg-amber-50/50 p-3 dark:border-amber-800 dark:bg-amber-950/30">
          <label
            htmlFor="aiOverviewMode"
            className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300"
          >
            AI Overview取得モード（検証用）
          </label>
          <select
            id="aiOverviewMode"
            name="aiOverviewMode"
            disabled={isLoading}
            value={aiOverviewMode}
            onChange={(event) =>
              setAiOverviewMode(event.target.value as AiOverviewProviderMode)
            }
            className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50 sm:w-auto"
          >
            {AI_OVERVIEW_MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
            この設定は検証用です。DataForSEO Live APIは、サーバー側の複数のゲートがすべて揃った場合のみ実行されます。
          </p>
          {aiOverviewMode === "dataforseo_live" && (
            <p className="mt-1 text-xs font-medium text-amber-800 dark:text-amber-300">
              Liveは課金が発生する可能性があります。Render側のLive許可envが揃っている場合のみ実行されます。
            </p>
          )}
        </div>
      )}

      {/* Dev/verification-only — see app/lib/analysis-request.ts's
          isChatGptModeSelectorEnabled(). Selecting "openai" here only
          sends chatgptMode in the request body; whether the Python API
          actually calls OpenAI still depends entirely on server-side
          gates (ALLOW_CHATGPT_MODE_OVERRIDE, an API key, the request
          limit) that this UI cannot change — and it's a no-op whenever
          the AI Overview section itself is "mock". */}
      {showChatGptModeSelector && (
        <div className="rounded-md border border-dashed border-amber-300 bg-amber-50/50 p-3 dark:border-amber-800 dark:bg-amber-950/30">
          <label
            htmlFor="chatgptMode"
            className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300"
          >
            ChatGPT観測モード（検証用）
          </label>
          <select
            id="chatgptMode"
            name="chatgptMode"
            disabled={isLoading}
            value={chatgptMode}
            onChange={(event) =>
              setChatgptMode(event.target.value as ChatGptProviderMode)
            }
            className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50 sm:w-auto"
          >
            {CHATGPT_MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
            OpenAI APIを使うには、サーバー側の許可とAPIキー設定が必要です。
          </p>
        </div>
      )}
    </form>
  );
}
