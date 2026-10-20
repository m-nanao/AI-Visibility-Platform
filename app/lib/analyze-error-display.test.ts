import { describe, expect, it } from "vitest";
import {
  formatAvailableAtInJst,
  resolveAnalyzeErrorDisplay,
  resolveAnalyzeQuotaDisplay,
} from "./analyze-error-display";

describe("resolveAnalyzeErrorDisplay — 401", () => {
  it("shows a login prompt for auth_required", () => {
    const display = resolveAnalyzeErrorDisplay(401, "auth_required", "authentication required");
    expect(display.kind).toBe("loginRequired");
    expect(display.showLoginLink).toBe(true);
    expect(display.message).not.toContain("成功");
  });

  it("shows a session-expired message distinct from loginRequired for invalid_token", () => {
    const display = resolveAnalyzeErrorDisplay(401, "invalid_token", "invalid token");
    expect(display.kind).toBe("sessionExpired");
    expect(display.showLoginLink).toBe(true);
    expect(display.message).toContain("再度ログイン");
  });

  it("falls back to loginRequired for an unrecognized 401 code", () => {
    const display = resolveAnalyzeErrorDisplay(401, null, "unauthorized");
    expect(display.kind).toBe("loginRequired");
  });
});

describe("resolveAnalyzeErrorDisplay — 400", () => {
  it("distinguishes projectId-required from a generic validation error", () => {
    const projectRequired = resolveAnalyzeErrorDisplay(
      400,
      "project_id_required",
      "projectId is required",
    );
    expect(projectRequired.kind).toBe("projectRequired");
    expect(projectRequired.showProjectReselect).toBe(true);

    const genericValidation = resolveAnalyzeErrorDisplay(400, null, "urls must not be empty");
    expect(genericValidation.kind).toBe("generic");
    expect(genericValidation.showProjectReselect).toBe(false);
    expect(genericValidation.message).toBe("urls must not be empty");
  });

  it("shows a generic reload message for request_id_required/request_id_invalid (not user-facing scenarios)", () => {
    for (const code of ["request_id_required", "request_id_invalid"]) {
      const display = resolveAnalyzeErrorDisplay(400, code, "requestId is required");
      expect(display.kind).toBe("generic");
      expect(display.message).toContain("再読み込み");
    }
  });
});

describe("resolveAnalyzeErrorDisplay — 403", () => {
  it("explains the project access denial and offers reselection", () => {
    const display = resolveAnalyzeErrorDisplay(403, "project_access_denied", "access denied");
    expect(display.kind).toBe("accessDenied");
    expect(display.showProjectReselect).toBe(true);
    expect(display.showLoginLink).toBe(false);
  });
});

describe("resolveAnalyzeErrorDisplay — 409", () => {
  it("still-running: never implies a new requestId should be issued", () => {
    const display = resolveAnalyzeErrorDisplay(409, "analysis_still_running", "still running");
    expect(display.kind).toBe("stillRunning");
    expect(display.message).toContain("処理中");
  });

  it("previously-failed: explains the uncertainty and extra-cost risk, prompts a fresh start", () => {
    const display = resolveAnalyzeErrorDisplay(
      409,
      "analysis_previously_failed",
      "previously failed",
    );
    expect(display.kind).toBe("previouslyFailed");
    expect(display.message).toContain("完全に終了したことを保証できない");
    expect(display.message).toContain("新しく分析を開始");
  });

  it("request-conflict: explains the input mismatch", () => {
    const display = resolveAnalyzeErrorDisplay(
      409,
      "analysis_request_conflict",
      "input conflict",
    );
    expect(display.kind).toBe("requestConflict");
    expect(display.message).toContain("内容が異なる");
  });

  it("request-cancelled: explains the deletion", () => {
    const display = resolveAnalyzeErrorDisplay(
      409,
      "analysis_request_cancelled",
      "cancelled",
    );
    expect(display.kind).toBe("requestCancelled");
    expect(display.message).toContain("削除");
  });

  it("falls back to the server message for an unrecognized 409 code", () => {
    const display = resolveAnalyzeErrorDisplay(409, "some_future_code", "some future reason");
    expect(display.kind).toBe("generic");
    expect(display.message).toBe("some future reason");
  });
});

describe("resolveAnalyzeErrorDisplay — 503", () => {
  it("distinguishes auth_unavailable from quota_enforcement_required from a generic 503", () => {
    const authUnavailable = resolveAnalyzeErrorDisplay(503, "auth_unavailable", "x");
    expect(authUnavailable.kind).toBe("authUnavailable");

    const quotaEnforcement = resolveAnalyzeErrorDisplay(
      503,
      "quota_enforcement_required",
      "x",
    );
    expect(quotaEnforcement.kind).toBe("quotaEnforcementRequired");
    expect(quotaEnforcement.message).toContain("管理者");

    const generic = resolveAnalyzeErrorDisplay(503, null, "x");
    expect(generic.kind).toBe("serviceUnavailable");
  });

  it("never shows internal env var names or config details in any 503 message", () => {
    for (const code of ["auth_unavailable", "quota_enforcement_required", null]) {
      const display = resolveAnalyzeErrorDisplay(503, code, "x");
      expect(display.message).not.toMatch(/ANALYZE_|_ENABLED|_REQUIRED=|env/i);
    }
  });
});

describe("resolveAnalyzeErrorDisplay — unknown status", () => {
  it("falls back to the server message", () => {
    const display = resolveAnalyzeErrorDisplay(500, null, "something broke");
    expect(display.kind).toBe("generic");
    expect(display.message).toBe("something broke");
  });

  it("never throws and always returns some message for an empty server message", () => {
    const display = resolveAnalyzeErrorDisplay(500, null, "");
    expect(display.message.length).toBeGreaterThan(0);
  });
});

describe("formatAvailableAtInJst", () => {
  it("converts a UTC ISO8601 timestamp to a JST-labeled display string", () => {
    // 2026-03-06T00:00:00Z == 2026-03-06 09:00 JST
    const result = formatAvailableAtInJst("2026-03-06T00:00:00+00:00");
    expect(result).toContain("2026");
    expect(result).toContain("3月6日");
    expect(result).toContain("9:00");
    expect(result).toContain("日本時間");
  });

  it("handles a UTC timestamp that rolls over to the next JST calendar day", () => {
    // 2026-03-05T20:00:00Z == 2026-03-06 05:00 JST
    const result = formatAvailableAtInJst("2026-03-05T20:00:00+00:00");
    expect(result).toContain("3月6日");
    expect(result).toContain("5:00");
  });

  it("returns null for a missing or unparseable value", () => {
    expect(formatAvailableAtInJst(undefined)).toBeNull();
    expect(formatAvailableAtInJst("not-a-date")).toBeNull();
  });
});

describe("resolveAnalyzeQuotaDisplay", () => {
  it("identifies a per-user limit distinctly from a per-project limit", () => {
    const userQuota = resolveAnalyzeQuotaDisplay(
      { scope: "user", metric: "all_analyses", period: "daily", availableAt: "2026-03-06T00:00:00+00:00" },
      "quota exceeded",
    );
    expect(userQuota.message).toContain("あなたの利用枠");

    const projectQuota = resolveAnalyzeQuotaDisplay(
      { scope: "project", metric: "all_analyses", period: "daily", availableAt: "2026-03-06T00:00:00+00:00" },
      "quota exceeded",
    );
    expect(projectQuota.message).toContain("プロジェクトの利用枠");
  });

  it("distinguishes the all-analyses limit from a specific paid-provider limit", () => {
    const all = resolveAnalyzeQuotaDisplay(
      { scope: "project", metric: "all_analyses", period: "daily" },
      "x",
    );
    expect(all.message).toContain("分析の実行回数");

    const dataforseoLive = resolveAnalyzeQuotaDisplay(
      { scope: "project", metric: "dataforseo_live", period: "daily" },
      "x",
    );
    expect(dataforseoLive.message).toContain("DataForSEO Live");

    const openai = resolveAnalyzeQuotaDisplay(
      { scope: "project", metric: "openai", period: "monthly" },
      "x",
    );
    expect(openai.message).toContain("ChatGPT観測");
  });

  it("distinguishes daily from monthly periods", () => {
    const daily = resolveAnalyzeQuotaDisplay(
      { scope: "project", metric: "all_analyses", period: "daily" },
      "x",
    );
    expect(daily.message).toContain("1日あたり");

    const monthly = resolveAnalyzeQuotaDisplay(
      { scope: "project", metric: "all_analyses", period: "monthly" },
      "x",
    );
    expect(monthly.message).toContain("1か月あたり");
  });

  it("shows the JST availableAt date when present", () => {
    const display = resolveAnalyzeQuotaDisplay(
      {
        scope: "project",
        metric: "all_analyses",
        period: "daily",
        availableAt: "2026-03-06T00:00:00+00:00",
      },
      "x",
    );
    expect(display.message).toContain("日本時間");
    expect(display.message).toContain("3月6日");
  });

  it("omits the availableAt sentence when it's missing, without throwing", () => {
    const display = resolveAnalyzeQuotaDisplay(
      { scope: "project", metric: "all_analyses", period: "daily" },
      "x",
    );
    expect(display.message).not.toContain("日本時間");
  });

  it("always includes the conservative 'may need admin reconfiguration' hedge, never asserting guaranteed availability", () => {
    const display = resolveAnalyzeQuotaDisplay(
      {
        scope: "project",
        metric: "dataforseo_live",
        period: "daily",
        availableAt: "2026-03-06T00:00:00+00:00",
      },
      "x",
    );
    expect(display.message).toContain("管理者");
    // Never an unconditional "利用可能になります" promise.
    expect(display.message).not.toMatch(/必ず利用可能|確実に利用可能/);
  });

  it("never shows raw scope_id/project_id or any token in the message", () => {
    const display = resolveAnalyzeQuotaDisplay(
      {
        scope: "project",
        metric: "all_analyses",
        period: "daily",
        availableAt: "2026-03-06T00:00:00+00:00",
      },
      "x",
    );
    expect(display.message).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/i);
  });

  it("falls back to the server message when quota is null/undefined", () => {
    expect(resolveAnalyzeQuotaDisplay(null, "server said this").message).toBe(
      "server said this",
    );
    expect(resolveAnalyzeQuotaDisplay(undefined, "server said this").message).toBe(
      "server said this",
    );
  });

  it("falls back gracefully for an unrecognized metric/scope/period (never fabricates a label)", () => {
    const display = resolveAnalyzeQuotaDisplay(
      { scope: "future-scope", metric: "future-metric", period: "future-period" },
      "x",
    );
    expect(display.message).toContain("future-metric");
  });
});
