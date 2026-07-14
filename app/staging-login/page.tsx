import { sanitizeNextPath } from "../lib/staging-auth";

export default async function StagingLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; next?: string }>;
}) {
  const params = await searchParams;
  const next = sanitizeNextPath(params.next);
  const hasError = params.error === "1";

  return (
    <div className="mx-auto flex min-h-full max-w-sm flex-1 flex-col justify-center gap-4 px-6 py-12">
      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
        依頼者確認用ステージング環境
      </h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        この環境は開発中の依頼者確認用ステージング環境です。案内されたパスコードを入力してください。
      </p>

      <form
        action={`/api/staging-auth?next=${encodeURIComponent(next)}`}
        method="POST"
        className="flex flex-col gap-3"
      >
        <input
          type="password"
          name="code"
          required
          autoFocus
          placeholder="パスコード"
          className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
        />
        {hasError && (
          <p className="text-sm text-rose-600 dark:text-rose-400">
            パスコードが正しくありません。
          </p>
        )}
        <button
          type="submit"
          className="inline-flex h-10 items-center justify-center rounded-md bg-zinc-900 px-5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          入室する
        </button>
      </form>

      <p className="text-xs text-zinc-400 dark:text-zinc-500">
        これは誤アクセス防止のための簡易的な仕組みであり、正式な認証ではありません。機密情報・個人情報・本番データはこの環境に入力しないでください。
      </p>
    </div>
  );
}
