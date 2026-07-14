import { NextResponse } from "next/server";
import { buildDummyAnalysis } from "../../lib/dummy-data";
import { parseAnalysisResult } from "../../lib/analysis-result-schema";
import type { AnalysisResult } from "../../lib/types";

const SIMULATED_ANALYSIS_DELAY_MS = 900;

// When `urls` is set, the Python API fetches up to MAX_URLS(10) pages
// with limited concurrency (3 at a time, ~5s timeout each — see
// backend/services/web_fetcher.py), so a slow/degraded batch of
// fetches can legitimately take up to ~ceil(10/3) * 5s = 20s before
// Python can respond. 3s (the original brandName-only timeout) was
// nowhere near enough once URL fetching was added. 25s gives a little
// headroom over that ~20s worst case while still failing fast enough
// that a genuinely stuck Python API doesn't hang the request forever.
const PYTHON_API_TIMEOUT_MS = 25_000;

type PythonApiOutcome =
  | { kind: "success"; data: AnalysisResult }
  // The Python API rejected *our request* (e.g. too many documents,
  // urls: []) — this is the caller's mistake, not a Python API
  // failure, so it must be reported back rather than silently
  // papered over with dummy data.
  | { kind: "validationError"; message: string }
  // Unset URL, network error, timeout, non-2xx (other than 400),
  // invalid JSON, or a response that doesn't match AnalysisResult.
  | { kind: "unavailable" };

/**
 * Tries the Python analysis API when PYTHON_ANALYSIS_API_URL is configured.
 * Every failure reason is logged (path + message only — never raw payloads
 * or headers, so no secrets end up in server logs).
 */
async function fetchFromPythonApi(
  brandName: string,
  documents?: string[],
  urls?: string[],
): Promise<PythonApiOutcome> {
  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) return { kind: "unavailable" };

  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(),
    PYTHON_API_TIMEOUT_MS,
  );

  const requestBody: { brandName: string; documents?: string[]; urls?: string[] } = {
    brandName,
  };
  if (documents) requestBody.documents = documents;
  if (urls) requestBody.urls = urls;

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
      signal: controller.signal,
    });

    if (response.status === 400 || response.status === 422) {
      // Both mean "the request we sent was invalid" (400: our own
      // validation errors like urls: []; 422: FastAPI's default
      // request-validation error shape, in case anything ever bypasses
      // our custom exception handler). Only trust the response body if
      // it's our own known-safe { error: string } shape — anything
      // else (e.g. FastAPI's raw `{ detail: [...] }` array of
      // validator internals) is replaced with a generic message rather
      // than shown to the user as-is.
      const errorBody = await response.json().catch(() => null);
      const message =
        errorBody && typeof errorBody.error === "string"
          ? errorBody.error
          : "入力内容を確認してください";
      return { kind: "validationError", message };
    }

    if (!response.ok) {
      console.warn(
        `[analyze] Python API returned HTTP ${response.status}; falling back to dummy data`,
      );
      return { kind: "unavailable" };
    }

    let json: unknown;
    try {
      json = await response.json();
    } catch {
      console.warn(
        "[analyze] Python API returned invalid JSON; falling back to dummy data",
      );
      return { kind: "unavailable" };
    }

    const parsed = parseAnalysisResult(json);
    if (!parsed.success) {
      console.warn(
        `[analyze] Python API response failed schema validation; falling back to dummy data (${parsed.reason})`,
      );
      return { kind: "unavailable" };
    }

    return { kind: "success", data: parsed.data };
  } catch (err) {
    const reason = err instanceof Error && err.name === "AbortError"
      ? "request timed out"
      : "request failed";
    console.warn(
      `[analyze] Python API ${reason}; falling back to dummy data`,
    );
    return { kind: "unavailable" };
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const brandName = body?.brandName;

  if (typeof brandName !== "string" || !brandName.trim()) {
    return NextResponse.json(
      { error: "brandName is required" },
      { status: 400 },
    );
  }

  const trimmedBrandName = brandName.trim();

  // Optional: an array of documents, or URLs to fetch, to run the
  // (Python-side) co-occurrence analysis on. Omitted/invalid -> forwarded
  // as undefined; the Python API then falls back per its own priority
  // (documents > urls > development sample documents).
  const documents = Array.isArray(body?.documents)
    ? body.documents.filter((doc: unknown): doc is string => typeof doc === "string")
    : undefined;
  const urls = Array.isArray(body?.urls)
    ? body.urls.filter((url: unknown): url is string => typeof url === "string")
    : undefined;

  const outcome = await fetchFromPythonApi(trimmedBrandName, documents, urls);

  if (outcome.kind === "success") {
    return NextResponse.json(outcome.data);
  }

  if (outcome.kind === "validationError") {
    return NextResponse.json({ error: outcome.message }, { status: 400 });
  }

  await new Promise((resolve) =>
    setTimeout(resolve, SIMULATED_ANALYSIS_DELAY_MS),
  );

  return NextResponse.json(buildDummyAnalysis(trimmedBrandName));
}
