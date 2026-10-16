import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildDummyAnalysis } from "./dummy-data";
import {
  buildAnalysisJobCreateRequestBody,
  buildAnalysisJobPath,
  clearPendingJobSubmission,
  getStatusHeading,
  isAsyncAnalysisEnabled,
  isDefinitiveCreateAnalysisJobOutcome,
  isTerminalJobStatus,
  resolveAnalysisJobResultOutcome,
  resolveAnalysisJobStatusOutcome,
  resolveCancelAnalysisJobOutcome,
  resolveCreateAnalysisJobOutcome,
  resolveIdempotencyKeyForJobSubmission,
  resolveMeProjectsOutcome,
} from "./analysis-jobs";

// This project's vitest run doesn't use a jsdom environment (no
// `window` global by default) — see
// app/lib/analysis-history.test.ts's printReport describe block for
// the same pattern. A tiny Map-backed fake sessionStorage is stubbed
// in only for the tests that need it.
function makeFakeWindow() {
  const store = new Map<string, string>();
  return {
    sessionStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
    },
  };
}

describe("isAsyncAnalysisEnabled", () => {
  const original = process.env.NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS;

  afterEach(() => {
    if (original === undefined) delete process.env.NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS;
    else process.env.NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS = original;
  });

  it("is false when unset", () => {
    delete process.env.NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS;
    expect(isAsyncAnalysisEnabled()).toBe(false);
  });

  it("is false for any value other than the exact string 'true'", () => {
    process.env.NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS = "1";
    expect(isAsyncAnalysisEnabled()).toBe(false);
  });

  it("is true only for the exact string 'true'", () => {
    process.env.NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS = "true";
    expect(isAsyncAnalysisEnabled()).toBe(true);
  });
});

describe("resolveMeProjectsOutcome", () => {
  it("returns 'error' for a null response (network failure)", async () => {
    const outcome = await resolveMeProjectsOutcome(null);
    expect(outcome.kind).toBe("error");
  });

  it("returns 'unauthorized' for 401", async () => {
    const outcome = await resolveMeProjectsOutcome(new Response(null, { status: 401 }));
    expect(outcome.kind).toBe("unauthorized");
  });

  it("returns 'unauthorized' for 403", async () => {
    const outcome = await resolveMeProjectsOutcome(new Response(null, { status: 403 }));
    expect(outcome.kind).toBe("unauthorized");
  });

  it("returns 'error' for an unexpected status", async () => {
    const outcome = await resolveMeProjectsOutcome(new Response(null, { status: 503 }));
    expect(outcome.kind).toBe("error");
  });

  it("returns 'error' when the body fails schema validation", async () => {
    const response = new Response(JSON.stringify({ projects: "not-an-array" }), { status: 200 });
    const outcome = await resolveMeProjectsOutcome(response);
    expect(outcome.kind).toBe("error");
  });

  it("returns the project ids on success", async () => {
    const response = new Response(
      JSON.stringify({ projects: [{ id: "project-a" }, { id: "project-b" }] }),
      { status: 200 },
    );
    const outcome = await resolveMeProjectsOutcome(response);
    expect(outcome).toEqual({ kind: "success", projectIds: ["project-a", "project-b"] });
  });

  it("returns an empty list (success) for a user with no projects", async () => {
    const response = new Response(JSON.stringify({ projects: [] }), { status: 200 });
    const outcome = await resolveMeProjectsOutcome(response);
    expect(outcome).toEqual({ kind: "success", projectIds: [] });
  });
});

describe("resolveIdempotencyKeyForJobSubmission", () => {
  beforeEach(() => {
    vi.stubGlobal("window", makeFakeWindow());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const USER_A = "user-a@example.com";
  const USER_B = "user-b@example.com";
  const content = { brandName: "Acme", urls: ["https://example.com"] };

  it("generates a key when no prior submission is stored", () => {
    const key = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    expect(key).toBe("key-1");
  });

  it("reuses the stored key for a retry of the exact same input (same user, same project, communication failure)", () => {
    const first = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    const second = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-2");

    expect(first).toBe("key-1");
    expect(second).toBe("key-1"); // reused, not "key-2"
  });

  it("reuses the stored key after a simulated reload (a fresh call with the same stored window)", () => {
    // sessionStorage genuinely survives a same-tab reload in a real
    // browser; makeFakeWindow()'s store persisting across calls
    // within this test is the correct abstraction for that.
    resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    const key = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-2");
    expect(key).toBe("key-1");
  });

  it("generates a new key when the brand name/content differs", () => {
    resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    const differentContent = { brandName: "Different Brand", urls: [] };
    const key = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", differentContent, () => "key-2");

    expect(key).toBe("key-2");
  });

  it("generates a new key when the urls/documents differ", () => {
    resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    const differentUrls = { brandName: "Acme", urls: ["https://different.example.com"] };
    const key = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", differentUrls, () => "key-2");

    expect(key).toBe("key-2");
  });

  it("generates a new key when a provider mode differs", () => {
    const withMode = { brandName: "Acme", urls: ["https://example.com"], chatgptMode: "off" as const };
    resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", withMode, () => "key-1");
    const differentMode = { ...withMode, chatgptMode: "openai" as const };
    const key = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", differentMode, () => "key-2");

    expect(key).toBe("key-2");
  });

  it("generates a new key when the projectId differs, even with identical content", () => {
    resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    const key = resolveIdempotencyKeyForJobSubmission(USER_A, "project-2", content, () => "key-2");

    expect(key).toBe("key-2");
  });

  it("generates a new key when a different user submits identical project/content (never reuses another user's key)", () => {
    resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    const key = resolveIdempotencyKeyForJobSubmission(USER_B, "project-1", content, () => "key-2");

    expect(key).toBe("key-2");
  });

  it("falls back to generating a fresh key when window/sessionStorage is unavailable", () => {
    vi.unstubAllGlobals(); // no window at all
    const key = resolveIdempotencyKeyForJobSubmission(USER_A, "project-1", content, () => "key-1");
    expect(key).toBe("key-1");
  });
});

describe("clearPendingJobSubmission", () => {
  it("removes the stored pending-submission record", () => {
    const fakeWindow = makeFakeWindow();
    vi.stubGlobal("window", fakeWindow);

    resolveIdempotencyKeyForJobSubmission(
      "user-a@example.com",
      "project-1",
      { brandName: "Acme" },
      () => "key-1",
    );
    expect(fakeWindow.sessionStorage.getItem("async-analysis-pending-job-submission")).not.toBeNull();

    clearPendingJobSubmission();

    expect(fakeWindow.sessionStorage.getItem("async-analysis-pending-job-submission")).toBeNull();

    vi.unstubAllGlobals();
  });

  it("does not throw when there is no window", () => {
    expect(() => clearPendingJobSubmission()).not.toThrow();
  });

  it("prevents a cleared key from being reused by a subsequent identical submission (202-accepted case)", () => {
    const fakeWindow = makeFakeWindow();
    vi.stubGlobal("window", fakeWindow);

    const content = { brandName: "Acme", urls: ["https://example.com"] };
    const first = resolveIdempotencyKeyForJobSubmission(
      "user-a@example.com",
      "project-1",
      content,
      () => "key-1",
    );
    clearPendingJobSubmission(); // simulates main.tsx after an "accepted" outcome

    const second = resolveIdempotencyKeyForJobSubmission(
      "user-a@example.com",
      "project-1",
      content,
      () => "key-2",
    );

    expect(first).toBe("key-1");
    expect(second).toBe("key-2"); // a fresh explicit submission, not a reuse

    vi.unstubAllGlobals();
  });
});

describe("buildAnalysisJobCreateRequestBody", () => {
  it("includes projectId/idempotencyKey alongside the analyze-request content", () => {
    const body = buildAnalysisJobCreateRequestBody(
      "project-1",
      "key-1",
      "Acme",
      ["https://example.com"],
    );

    expect(body).toEqual({
      brandName: "Acme",
      urls: ["https://example.com"],
      projectId: "project-1",
      idempotencyKey: "key-1",
    });
  });

  it("omits urls when none were given, mirroring buildAnalyzeRequestBody", () => {
    const body = buildAnalysisJobCreateRequestBody("project-1", "key-1", "Acme", []);
    expect(body.urls).toBeUndefined();
  });
});

describe("resolveCreateAnalysisJobOutcome", () => {
  it("returns 'error' for a null response", async () => {
    const outcome = await resolveCreateAnalysisJobOutcome(null);
    expect(outcome.kind).toBe("error");
  });

  it("maps 404 to 'disabled' (the job API is off)", async () => {
    const outcome = await resolveCreateAnalysisJobOutcome(new Response(null, { status: 404 }));
    expect(outcome.kind).toBe("disabled");
  });

  it("maps 401 to 'unauthorized'", async () => {
    const outcome = await resolveCreateAnalysisJobOutcome(new Response(null, { status: 401 }));
    expect(outcome.kind).toBe("unauthorized");
  });

  it("maps 403 to 'forbidden'", async () => {
    const outcome = await resolveCreateAnalysisJobOutcome(new Response(null, { status: 403 }));
    expect(outcome.kind).toBe("forbidden");
  });

  it("maps 409 to 'conflict'", async () => {
    const outcome = await resolveCreateAnalysisJobOutcome(new Response(null, { status: 409 }));
    expect(outcome.kind).toBe("conflict");
  });

  it("maps 429 to 'rateLimited'", async () => {
    const outcome = await resolveCreateAnalysisJobOutcome(new Response(null, { status: 429 }));
    expect(outcome.kind).toBe("rateLimited");
  });

  it("maps 400 to 'invalidInput' using the backend's error message", async () => {
    const response = new Response(JSON.stringify({ error: "brandName is required" }), {
      status: 400,
    });
    const outcome = await resolveCreateAnalysisJobOutcome(response);
    expect(outcome).toEqual({ kind: "invalidInput", message: "brandName is required" });
  });

  it("maps an unexpected status to 'error'", async () => {
    const outcome = await resolveCreateAnalysisJobOutcome(new Response(null, { status: 500 }));
    expect(outcome.kind).toBe("error");
  });

  it("maps 202 with a valid body to 'accepted'", async () => {
    const response = new Response(
      JSON.stringify({ analysisRunId: "run-1", status: "queued" }),
      { status: 202 },
    );
    const outcome = await resolveCreateAnalysisJobOutcome(response);
    expect(outcome).toEqual({ kind: "accepted", analysisRunId: "run-1", status: "queued" });
  });

  it("maps 202 with an invalid body to 'error'", async () => {
    const response = new Response(JSON.stringify({ not: "the right shape" }), { status: 202 });
    const outcome = await resolveCreateAnalysisJobOutcome(response);
    expect(outcome.kind).toBe("error");
  });
});

describe("isDefinitiveCreateAnalysisJobOutcome", () => {
  it("is true for 'accepted'", () => {
    expect(
      isDefinitiveCreateAnalysisJobOutcome({ kind: "accepted", analysisRunId: "1", status: "queued" }),
    ).toBe(true);
  });

  it("is true for every rejection outcome", () => {
    expect(isDefinitiveCreateAnalysisJobOutcome({ kind: "forbidden", message: "x" })).toBe(true);
    expect(isDefinitiveCreateAnalysisJobOutcome({ kind: "conflict", message: "x" })).toBe(true);
    expect(isDefinitiveCreateAnalysisJobOutcome({ kind: "invalidInput", message: "x" })).toBe(true);
  });

  it("is false for 'error' (a retry should reuse the same idempotency key)", () => {
    expect(isDefinitiveCreateAnalysisJobOutcome({ kind: "error", message: "x" })).toBe(false);
  });
});

describe("buildAnalysisJobPath", () => {
  it("builds /analysis/jobs/{id}", () => {
    expect(buildAnalysisJobPath("abc-123")).toBe("/analysis/jobs/abc-123");
  });

  it("URL-encodes the id", () => {
    expect(buildAnalysisJobPath("a/b")).toBe("/analysis/jobs/a%2Fb");
  });
});

describe("resolveAnalysisJobStatusOutcome", () => {
  it("returns 'error' for a null response", async () => {
    const outcome = await resolveAnalysisJobStatusOutcome(null);
    expect(outcome.kind).toBe("error");
  });

  it("maps 401 to 'unauthorized'", async () => {
    const outcome = await resolveAnalysisJobStatusOutcome(new Response(null, { status: 401 }));
    expect(outcome.kind).toBe("unauthorized");
  });

  it("maps 403 to 'forbidden'", async () => {
    const outcome = await resolveAnalysisJobStatusOutcome(new Response(null, { status: 403 }));
    expect(outcome.kind).toBe("forbidden");
  });

  it("maps 404 to 'notFound'", async () => {
    const outcome = await resolveAnalysisJobStatusOutcome(new Response(null, { status: 404 }));
    expect(outcome.kind).toBe("notFound");
  });

  it("parses a valid status body", async () => {
    const response = new Response(
      JSON.stringify({
        analysisRunId: "run-1",
        status: "running",
        startedAt: "2026-01-01T00:00:00Z",
        completedAt: null,
        errorMessage: null,
      }),
      { status: 200 },
    );
    const outcome = await resolveAnalysisJobStatusOutcome(response);
    expect(outcome).toEqual({
      kind: "status",
      job: {
        analysisRunId: "run-1",
        status: "running",
        startedAt: "2026-01-01T00:00:00Z",
        completedAt: undefined,
        errorMessage: undefined,
      },
    });
  });

  it("returns 'error' when the body fails schema validation", async () => {
    const response = new Response(JSON.stringify({ not: "valid" }), { status: 200 });
    const outcome = await resolveAnalysisJobStatusOutcome(response);
    expect(outcome.kind).toBe("error");
  });
});

describe("isTerminalJobStatus", () => {
  it("is true for completed/partial/failed", () => {
    expect(isTerminalJobStatus("completed")).toBe(true);
    expect(isTerminalJobStatus("partial")).toBe(true);
    expect(isTerminalJobStatus("failed")).toBe(true);
  });

  it("is false for queued/running", () => {
    expect(isTerminalJobStatus("queued")).toBe(false);
    expect(isTerminalJobStatus("running")).toBe(false);
  });
});

describe("getStatusHeading", () => {
  it("returns Japanese headings for every known status", () => {
    expect(getStatusHeading("queued")).toBe("分析受付済み");
    expect(getStatusHeading("running")).toBe("分析中");
    expect(getStatusHeading("completed")).toBe("分析完了");
    expect(getStatusHeading("partial")).toBe("一部の結果が利用可能です");
    expect(getStatusHeading("failed")).toBe("分析に失敗しました");
  });

  it("falls back to the raw status for an unrecognized value", () => {
    expect(getStatusHeading("something-new")).toBe("something-new");
  });
});

describe("resolveAnalysisJobResultOutcome", () => {
  it("returns 'error' for a null response", async () => {
    const outcome = await resolveAnalysisJobResultOutcome(null);
    expect(outcome.kind).toBe("error");
  });

  it("maps 401 to 'unauthorized'", async () => {
    const outcome = await resolveAnalysisJobResultOutcome(new Response(null, { status: 401 }));
    expect(outcome.kind).toBe("unauthorized");
  });

  it("maps 403 to 'forbidden'", async () => {
    const outcome = await resolveAnalysisJobResultOutcome(new Response(null, { status: 403 }));
    expect(outcome.kind).toBe("forbidden");
  });

  it("maps 404 to 'notFound'", async () => {
    const outcome = await resolveAnalysisJobResultOutcome(new Response(null, { status: 404 }));
    expect(outcome.kind).toBe("notFound");
  });

  it("maps 409 to 'notReady' (job not finished yet)", async () => {
    const outcome = await resolveAnalysisJobResultOutcome(new Response(null, { status: 409 }));
    expect(outcome).toEqual({ kind: "notReady" });
  });

  it("maps a failed job (200, status=failed, no result) to 'failed'", async () => {
    const response = new Response(
      JSON.stringify({
        analysisRunId: "run-1",
        status: "failed",
        errorMessage: "unexpected error while running analysis",
        result: null,
        meta: null,
      }),
      { status: 200 },
    );
    const outcome = await resolveAnalysisJobResultOutcome(response);
    expect(outcome).toEqual({
      kind: "failed",
      errorMessage: "unexpected error while running analysis",
    });
  });

  it("never treats an empty placeholder result ({}) as a success", async () => {
    // Should not happen on a real backend (status would never be
    // 'completed'/'partial' with an empty result), but this is the
    // exact failure mode docs/40 "13.2" warns about, so it gets an
    // explicit regression test.
    const response = new Response(
      JSON.stringify({
        analysisRunId: "run-1",
        status: "completed",
        errorMessage: null,
        result: {},
        meta: null,
      }),
      { status: 200 },
    );
    const outcome = await resolveAnalysisJobResultOutcome(response);
    expect(outcome.kind).toBe("incompatible");
  });

  it("maps a null result on a 'completed' status to 'incompatible'", async () => {
    const response = new Response(
      JSON.stringify({
        analysisRunId: "run-1",
        status: "completed",
        errorMessage: null,
        result: null,
        meta: null,
      }),
      { status: 200 },
    );
    const outcome = await resolveAnalysisJobResultOutcome(response);
    expect(outcome.kind).toBe("incompatible");
  });

  it("maps a result that fails AnalysisResult validation to 'incompatible'", async () => {
    const response = new Response(
      JSON.stringify({
        analysisRunId: "run-1",
        status: "completed",
        errorMessage: null,
        result: { not: "a valid AnalysisResult" },
        meta: null,
      }),
      { status: 200 },
    );
    const outcome = await resolveAnalysisJobResultOutcome(response);
    expect(outcome.kind).toBe("incompatible");
  });

  it("maps a valid completed result to 'success'", async () => {
    const result = buildDummyAnalysis("Acme");
    const response = new Response(
      JSON.stringify({
        analysisRunId: "run-1",
        status: "completed",
        errorMessage: null,
        result,
        meta: result.meta,
      }),
      { status: 200 },
    );
    const outcome = await resolveAnalysisJobResultOutcome(response);
    expect(outcome.kind).toBe("success");
    if (outcome.kind === "success") {
      expect(outcome.result.brandName).toBe("Acme");
      expect(outcome.status).toBe("completed");
    }
  });

  it("maps a valid partial result to 'success' with status='partial'", async () => {
    const result = buildDummyAnalysis("Acme");
    const response = new Response(
      JSON.stringify({
        analysisRunId: "run-1",
        status: "partial",
        errorMessage: null,
        result,
        meta: result.meta,
      }),
      { status: 200 },
    );
    const outcome = await resolveAnalysisJobResultOutcome(response);
    expect(outcome.kind).toBe("success");
    if (outcome.kind === "success") {
      expect(outcome.status).toBe("partial");
    }
  });
});

describe("resolveCancelAnalysisJobOutcome", () => {
  it("returns 'error' for a null response (network failure)", async () => {
    const outcome = await resolveCancelAnalysisJobOutcome(null);
    expect(outcome.kind).toBe("error");
  });

  it("maps 401 to 'unauthorized'", async () => {
    const outcome = await resolveCancelAnalysisJobOutcome(new Response(null, { status: 401 }));
    expect(outcome.kind).toBe("unauthorized");
  });

  it("maps 403 to 'forbidden' (not this job's creator, or it doesn't exist)", async () => {
    const outcome = await resolveCancelAnalysisJobOutcome(new Response(null, { status: 403 }));
    expect(outcome.kind).toBe("forbidden");
  });

  it("maps 404 to 'notFound'", async () => {
    const outcome = await resolveCancelAnalysisJobOutcome(new Response(null, { status: 404 }));
    expect(outcome.kind).toBe("notFound");
  });

  it("maps 409 to 'conflict' (no longer queued)", async () => {
    const response = new Response(
      JSON.stringify({ error: "analysis job can no longer be cancelled" }),
      { status: 409 },
    );
    const outcome = await resolveCancelAnalysisJobOutcome(response);
    expect(outcome.kind).toBe("conflict");
  });

  it("maps an unexpected status to 'error'", async () => {
    const outcome = await resolveCancelAnalysisJobOutcome(new Response(null, { status: 500 }));
    expect(outcome.kind).toBe("error");
  });

  it("returns 'cancelled' for a 200 with cancelled: true", async () => {
    const response = new Response(JSON.stringify({ cancelled: true }), { status: 200 });
    const outcome = await resolveCancelAnalysisJobOutcome(response);
    expect(outcome.kind).toBe("cancelled");
  });

  it("returns 'error' for a 200 whose body doesn't confirm cancellation", async () => {
    const response = new Response(JSON.stringify({ ok: true }), { status: 200 });
    const outcome = await resolveCancelAnalysisJobOutcome(response);
    expect(outcome.kind).toBe("error");
  });

  it("returns 'error' for a 200 with unparseable JSON", async () => {
    const response = new Response("not json", { status: 200 });
    const outcome = await resolveCancelAnalysisJobOutcome(response);
    expect(outcome.kind).toBe("error");
  });
});
