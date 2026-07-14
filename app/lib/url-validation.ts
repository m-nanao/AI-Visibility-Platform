// Mirrors backend/models.py's MAX_URLS. Kept in sync manually since
// the two live in different languages/runtimes.
export const MAX_URLS = 10;

export interface ValidatedUrlsInput {
  /** Valid, deduplicated URLs, in input order, capped at MAX_URLS. */
  urls: string[];
  /** Human-readable problems to show the user. Non-empty -> don't submit. */
  errors: string[];
}

function isHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Parses the raw contents of the "one URL per line" textarea into a
 * validated, deduplicated list.
 *
 * - Blank lines are silently ignored.
 * - A line that isn't a valid http(s) URL is reported as an error and
 *   excluded from the result.
 * - Duplicate URLs (after trimming) are silently deduplicated —
 *   keeping the first occurrence — rather than reported as an error.
 * - More than MAX_URLS valid, unique URLs is reported as an error.
 *
 * This only checks what a browser reasonably can (scheme, well-formed
 * URL syntax, count, duplicates). Rejecting localhost/private IPs is
 * still done authoritatively on the Python side (see
 * backend/services/web_fetcher.py) since that requires a DNS lookup.
 */
export function validateUrlsInput(rawInput: string): ValidatedUrlsInput {
  const lines = rawInput
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  const errors: string[] = [];
  const seen = new Set<string>();
  const urls: string[] = [];

  for (const line of lines) {
    if (!isHttpUrl(line)) {
      errors.push(`「${line}」はhttp(s)://で始まる正しいURLではありません`);
      continue;
    }
    if (seen.has(line)) continue;
    seen.add(line);
    urls.push(line);
  }

  if (urls.length > MAX_URLS) {
    errors.push(
      `URLは最大${MAX_URLS}件までにしてください（現在${urls.length}件）`,
    );
  }

  return { urls: urls.slice(0, MAX_URLS), errors };
}
