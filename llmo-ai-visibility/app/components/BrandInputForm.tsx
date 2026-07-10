"use client";

import { useState, type FormEvent } from "react";

export default function BrandInputForm({
  onSubmit,
  isLoading,
  initialValue = "",
}: {
  onSubmit: (brandName: string) => void;
  isLoading: boolean;
  initialValue?: string;
}) {
  const [brandName, setBrandName] = useState(initialValue);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = brandName.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 sm:flex-row sm:items-end"
    >
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
          value={brandName}
          onChange={(event) => setBrandName(event.target.value)}
          placeholder="例: サンプル株式会社"
          className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
        />
      </div>
      <button
        type="submit"
        disabled={isLoading || !brandName.trim()}
        className="inline-flex h-10 items-center justify-center rounded-md bg-zinc-900 px-5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        {isLoading ? "分析中..." : "分析開始"}
      </button>
    </form>
  );
}
