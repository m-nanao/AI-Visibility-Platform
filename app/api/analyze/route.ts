import { NextResponse } from "next/server";
import { buildDummyAnalysis } from "../../lib/dummy-data";

const SIMULATED_ANALYSIS_DELAY_MS = 900;
const PYTHON_API_TIMEOUT_MS = 3000;

/**
 * Tries the Python analysis API when PYTHON_ANALYSIS_API_URL is configured.
 * Returns null on any failure (unset URL, network error, timeout, non-2xx),
 * so the caller can fall back to the local dummy data.
 */
async function fetchFromPythonApi(
  brandName: string,
): Promise<unknown | null> {
  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) return null;

  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(),
    PYTHON_API_TIMEOUT_MS,
  );

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brandName }),
      signal: controller.signal,
    });

    if (!response.ok) return null;
    return await response.json();
  } catch {
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

  const pythonResult = await fetchFromPythonApi(trimmedBrandName);
  if (pythonResult) {
    return NextResponse.json(pythonResult);
  }

  await new Promise((resolve) =>
    setTimeout(resolve, SIMULATED_ANALYSIS_DELAY_MS),
  );

  return NextResponse.json(buildDummyAnalysis(trimmedBrandName));
}
