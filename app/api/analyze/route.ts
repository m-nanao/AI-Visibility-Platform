import { NextResponse } from "next/server";
import { buildDummyAnalysis } from "../../lib/dummy-data";
import { parseAnalysisResult } from "../../lib/analysis-result-schema";
import type { AnalysisResult } from "../../lib/types";

const SIMULATED_ANALYSIS_DELAY_MS = 900;
const PYTHON_API_TIMEOUT_MS = 3000;

/**
 * Tries the Python analysis API when PYTHON_ANALYSIS_API_URL is configured.
 * Returns null on any failure (unset URL, network error, timeout, non-2xx,
 * invalid JSON, or a response that doesn't match AnalysisResult), so the
 * caller can fall back to the local dummy data. Every failure reason is
 * logged (path + message only — never raw payloads or headers, so no
 * secrets end up in server logs).
 */
async function fetchFromPythonApi(
  brandName: string,
  documents?: string[],
  urls?: string[],
): Promise<AnalysisResult | null> {
  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) return null;

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

    if (!response.ok) {
      console.warn(
        `[analyze] Python API returned HTTP ${response.status}; falling back to dummy data`,
      );
      return null;
    }

    let json: unknown;
    try {
      json = await response.json();
    } catch {
      console.warn(
        "[analyze] Python API returned invalid JSON; falling back to dummy data",
      );
      return null;
    }

    const parsed = parseAnalysisResult(json);
    if (!parsed.success) {
      console.warn(
        `[analyze] Python API response failed schema validation; falling back to dummy data (${parsed.reason})`,
      );
      return null;
    }

    return parsed.data;
  } catch (err) {
    const reason = err instanceof Error && err.name === "AbortError"
      ? "request timed out"
      : "request failed";
    console.warn(
      `[analyze] Python API ${reason}; falling back to dummy data`,
    );
    return null;
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

  const pythonResult = await fetchFromPythonApi(trimmedBrandName, documents, urls);
  if (pythonResult) {
    return NextResponse.json(pythonResult);
  }

  await new Promise((resolve) =>
    setTimeout(resolve, SIMULATED_ANALYSIS_DELAY_MS),
  );

  return NextResponse.json(buildDummyAnalysis(trimmedBrandName));
}
