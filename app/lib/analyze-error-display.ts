/**
 * Turns POST /api/analyze's error responses into user-facing Japanese
 * copy (Task 6-B5, feature/sync-analyze-jwt-project-auth). Kept as
 * pure functions, separate from app/page.tsx, specifically so this
 * logic is unit-testable without a React component-test harness (this
 * project has none — see app/lib/analysis-jobs.test.ts's own
 * makeFakeWindow()-based convention for the same reasoning).
 *
 * Every `code` value consulted here is one Task 6-B2/6-B3/6-B4 already
 * define and forward end-to-end (backend/main.py's error_response()
 * `code` param -> app/api/analyze/route.ts's PythonApiOutcome ->
 * app/page.tsx) — never a guessed/invented code. See each function's
 * own comment for exactly which backend constant it mirrors.
 */

import {
  ANALYZE_PREVIOUSLY_FAILED_CODE,
  ANALYZE_REQUEST_CANCELLED_CODE,
  ANALYZE_REQUEST_CONFLICT_CODE,
  ANALYZE_STILL_RUNNING_CODE,
  type AnalyzeQuotaInfo,
} from "./analysis-request";

export type AnalyzeErrorKind =
  | "loginRequired"
  | "sessionExpired"
  | "projectRequired"
  | "accessDenied"
  | "stillRunning"
  | "previouslyFailed"
  | "requestConflict"
  | "requestCancelled"
  | "quotaExceeded"
  | "authUnavailable"
  | "quotaEnforcementRequired"
  | "serviceUnavailable"
  | "generic";

export interface AnalyzeErrorDisplay {
  kind: AnalyzeErrorKind;
  /** Short heading. */
  title: string;
  /** Full explanation shown to the user. */
  message: string;
  /** Show a "ログインする" link (app/login). */
  showLoginLink: boolean;
  /** Show a "プロジェクトを選びなおす" affordance (re-fetch/re-select
   * from GET /api/me/projects — never a link to a status-check API
   * this app doesn't have). */
  showProjectReselect: boolean;
}

// --- 401 ------------------------------------------------------------

/** Must match backend/main.py's ANALYZE_AUTH_REQUIRED_CODE. */
export const ANALYZE_ERROR_CODE_AUTH_REQUIRED = "auth_required";
/** Must match backend/main.py's ANALYZE_INVALID_TOKEN_CODE. */
export const ANALYZE_ERROR_CODE_INVALID_TOKEN = "invalid_token";
// --- 400 --------------------------------------------------------------
/** Must match backend/main.py's ANALYZE_PROJECT_ID_REQUIRED_CODE. */
export const ANALYZE_ERROR_CODE_PROJECT_ID_REQUIRED = "project_id_required";
/** Must match backend/main.py's ANALYZE_REQUEST_ID_REQUIRED_CODE. */
export const ANALYZE_ERROR_CODE_REQUEST_ID_REQUIRED = "request_id_required";
/** Must match backend/main.py's ANALYZE_REQUEST_ID_INVALID_CODE. */
export const ANALYZE_ERROR_CODE_REQUEST_ID_INVALID = "request_id_invalid";
// --- 409 codes consumed below are imported from analysis-request.ts
// (already defined/consumed there by isTerminalAnalyzeConflictCode()/
// getAnalyzeConflictMessage()) — reused by name, not redefined, so
// there is exactly one source of truth for each 409 code string.
// --- 503 --------------------------------------------------------------
/** Must match backend/main.py's ANALYZE_AUTH_UNAVAILABLE_CODE. */
export const ANALYZE_ERROR_CODE_AUTH_UNAVAILABLE = "auth_unavailable";
/** Must match backend/main.py's ANALYZE_QUOTA_ENFORCEMENT_REQUIRED_CODE
 * (Task 6-B4). */
export const ANALYZE_ERROR_CODE_QUOTA_ENFORCEMENT_REQUIRED = "quota_enforcement_required";

/**
 * Resolves a non-2xx, non-429 POST /api/analyze response into display
 * copy. `serverMessage` is the backend's own `error` text — used only
 * as a last-resort fallback for a status/code combination this
 * function doesn't have specific copy for, so a legitimate but
 * unanticipated backend message is never silently swallowed.
 */
export function resolveAnalyzeErrorDisplay(
  status: number,
  code: string | null,
  serverMessage: string,
): AnalyzeErrorDisplay {
  if (status === 401) {
    if (code === ANALYZE_ERROR_CODE_INVALID_TOKEN) {
      return {
        kind: "sessionExpired",
        title: "セッションが切れました",
        message: "ログインの有効期限が切れています。再度ログインしてください。",
        showLoginLink: true,
        showProjectReselect: false,
      };
    }
    // ANALYZE_ERROR_CODE_AUTH_REQUIRED or any unrecognized 401 code —
    // treated the same way: not signed in at all.
    return {
      kind: "loginRequired",
      title: "ログインが必要です",
      message: "この分析を実行するにはログインが必要です。",
      showLoginLink: true,
      showProjectReselect: false,
    };
  }

  if (status === 400) {
    if (code === ANALYZE_ERROR_CODE_PROJECT_ID_REQUIRED) {
      return {
        kind: "projectRequired",
        title: "プロジェクトを選択してください",
        message: "分析を実行するプロジェクトを選択してください。",
        showLoginLink: false,
        showProjectReselect: true,
      };
    }
    if (
      code === ANALYZE_ERROR_CODE_REQUEST_ID_REQUIRED ||
      code === ANALYZE_ERROR_CODE_REQUEST_ID_INVALID
    ) {
      // Not a normal user-facing scenario (requestId is generated
      // automatically) — if it ever happens, it means something is
      // wrong with this client's own state, not the user's input.
      return {
        kind: "generic",
        title: "分析を開始できませんでした",
        message: "ページを再読み込みしてから、もう一度お試しください。",
        showLoginLink: false,
        showProjectReselect: false,
      };
    }
    // Every other 400 (e.g. "urls must not be empty", "brandName is
    // required") is a genuine input-validation error distinct from
    // the project-selection case above — shown as the backend worded
    // it, since this app has no more specific copy for arbitrary
    // input errors.
    return {
      kind: "generic",
      title: "入力内容を確認してください",
      message: serverMessage,
      showLoginLink: false,
      showProjectReselect: false,
    };
  }

  if (status === 403) {
    return {
      kind: "accessDenied",
      title: "このプロジェクトにアクセスできません",
      message:
        "選択されているプロジェクトで分析を実行する権限がありません。プロジェクトを選びなおすか、管理者にアクセス権限の付与を依頼してください。",
      showLoginLink: false,
      showProjectReselect: true,
    };
  }

  if (status === 409) {
    if (code === ANALYZE_STILL_RUNNING_CODE) {
      return {
        kind: "stillRunning",
        title: "この分析は処理中です",
        message:
          "同じ内容の分析が既に処理中です。しばらく時間をおいてから、同じ内容で再度お試しください。",
        showLoginLink: false,
        showProjectReselect: false,
      };
    }
    if (code === ANALYZE_PREVIOUSLY_FAILED_CODE) {
      return {
        kind: "previouslyFailed",
        title: "前回の分析は失敗しました",
        message:
          "直前の分析は失敗したため、同じ内容では再実行できません。外部サービスへの呼び出しが完全に終了したことを保証できないため、追加の費用が発生している可能性があります。入力内容を確認し、新しく分析を開始してください。",
        showLoginLink: false,
        showProjectReselect: false,
      };
    }
    if (code === ANALYZE_REQUEST_CONFLICT_CODE) {
      return {
        kind: "requestConflict",
        title: "入力内容が変更されています",
        message:
          "直前に開始した分析と内容が異なるため、同じ操作として扱えません。内容を確認し、もう一度分析を開始してください。",
        showLoginLink: false,
        showProjectReselect: false,
      };
    }
    if (code === ANALYZE_REQUEST_CANCELLED_CODE) {
      return {
        kind: "requestCancelled",
        title: "この分析は削除されています",
        message: "この分析は削除済みのため再利用できません。新しく分析を開始してください。",
        showLoginLink: false,
        showProjectReselect: false,
      };
    }
    return {
      kind: "generic",
      title: "分析を開始できませんでした",
      message: serverMessage,
      showLoginLink: false,
      showProjectReselect: false,
    };
  }

  if (status === 503) {
    if (code === ANALYZE_ERROR_CODE_AUTH_UNAVAILABLE) {
      return {
        kind: "authUnavailable",
        title: "認証機能に問題が発生しています",
        message:
          "認証機能に一時的な問題が発生しているため、分析を実行できません。しばらくしてから再度お試しください。解消しない場合は管理者にお問い合わせください。",
        showLoginLink: false,
        showProjectReselect: false,
      };
    }
    if (code === ANALYZE_ERROR_CODE_QUOTA_ENFORCEMENT_REQUIRED) {
      return {
        kind: "quotaEnforcementRequired",
        title: "利用枠の設定が完了していません",
        message:
          "この環境では利用枠の保護設定が完了していないため、分析を安全に実行できません。管理者による設定が必要です。しばらくしてから再度お試しいただくか、管理者にお問い合わせください。",
        showLoginLink: false,
        showProjectReselect: false,
      };
    }
    return {
      kind: "serviceUnavailable",
      title: "サービスに一時的な問題が発生しています",
      message: "しばらくしてから再度お試しください。解消しない場合は管理者にお問い合わせください。",
      showLoginLink: false,
      showProjectReselect: false,
    };
  }

  return {
    kind: "generic",
    title: "分析中にエラーが発生しました",
    message: serverMessage || "時間をおいて再度お試しください。",
    showLoginLink: false,
    showProjectReselect: false,
  };
}

// --- 429 usage-quota display (Task 6-B4/6-B5) ---------------------------
//
// Note: the backend's `quota` object (see backend/main.py's
// _analyze_authenticated_idempotent()) does not currently include the
// configured `limit` value — only scope/metric/period/availableAt.
// This means the Frontend cannot specifically detect "the limit is
// configured to 0" (a case this task explicitly asks to word
// differently — "管理者による設定変更が必要な場合があります"). Rather
// than guess, every 429 message below is phrased conservatively
// regardless of the actual limit, so it stays accurate whether or not
// the limit is 0 — see this task's completion report for a proposed
// (not implemented) minimal backend addition to resolve this more
// precisely in the future.

const QUOTA_SCOPE_LABELS: Record<string, string> = {
  user: "あなたの利用枠",
  project: "プロジェクトの利用枠",
};

const QUOTA_METRIC_LABELS: Record<string, string> = {
  all_analyses: "分析の実行回数",
  dataforseo_sandbox: "DataForSEO Sandbox（AI Overview比較、検証用）",
  dataforseo_live: "DataForSEO Live（AI Overview比較）",
  openai: "ChatGPT観測",
  anthropic: "Claude観測",
  google: "Gemini観測",
};

const QUOTA_PERIOD_LABELS: Record<string, string> = {
  daily: "1日あたり",
  monthly: "1か月あたり",
};

/** Falls back to the raw value (never fabricated) when it's not one
 * of the known values — a future metric/scope/period this app
 * doesn't know about yet is still shown, just without a friendly
 * label. */
function describeQuotaScope(scope: string | undefined): string {
  if (!scope) return "利用枠";
  return QUOTA_SCOPE_LABELS[scope] ?? `利用枠（${scope}）`;
}

function describeQuotaMetric(metric: string | undefined): string {
  if (!metric) return "";
  return QUOTA_METRIC_LABELS[metric] ?? metric;
}

function describeQuotaPeriod(period: string | undefined): string {
  if (!period) return "";
  return QUOTA_PERIOD_LABELS[period] ?? period;
}

/**
 * Converts the `quota.availableAt` UTC ISO8601 timestamp the backend
 * sends into a JST ("日本時間") display string — the API always
 * returns UTC (see backend/main.py's `next_period_start.isoformat()`,
 * a timezone-aware UTC datetime), so this app must never show it
 * as-is. Returns null for a missing/unparseable value rather than
 * throwing — callers must handle that by omitting the "次に利用可能
 * になる日時" line entirely rather than showing something broken.
 */
export function formatAvailableAtInJst(availableAt: string | undefined): string | null {
  if (!availableAt) return null;
  const date = new Date(availableAt);
  if (Number.isNaN(date.getTime())) return null;
  try {
    return (
      new Intl.DateTimeFormat("ja-JP", {
        timeZone: "Asia/Tokyo",
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }).format(date) + "（日本時間）"
    );
  } catch {
    return null;
  }
}

/**
 * Builds the full 429 (analysis_quota_exceeded) display message —
 * see this module's own comment above for why the limit=0 case is
 * always hedged rather than specifically detected.
 */
export function resolveAnalyzeQuotaDisplay(
  quota: AnalyzeQuotaInfo | null | undefined,
  serverMessage: string,
): AnalyzeErrorDisplay {
  if (!quota) {
    return {
      kind: "quotaExceeded",
      title: "利用上限に達しています",
      message: serverMessage || "利用上限に達しているため、分析を開始できません。",
      showLoginLink: false,
      showProjectReselect: false,
    };
  }

  const scopeLabel = describeQuotaScope(quota.scope);
  const metricLabel = describeQuotaMetric(quota.metric);
  const periodLabel = describeQuotaPeriod(quota.period);
  const availableAtLabel = formatAvailableAtInJst(quota.availableAt);

  const parts: string[] = [];
  parts.push(
    `${scopeLabel}${metricLabel ? `（${metricLabel}${periodLabel ? "・" + periodLabel : ""}）` : ""}の上限に達しました。`,
  );
  if (availableAtLabel) {
    parts.push(`${availableAtLabel}以降に利用可能になる予定です。`);
  }
  // Always shown, regardless of whether the limit is known to be 0 —
  // see module comment.
  parts.push(
    "運用設定により、上記の日時になっても利用できない場合があります。解消しない場合は管理者による利用枠設定の確認が必要な場合があります。",
  );

  return {
    kind: "quotaExceeded",
    title: "利用上限に達しています",
    message: parts.join(""),
    showLoginLink: false,
    showProjectReselect: false,
  };
}
