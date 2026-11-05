/**
 * Validate a post login `next` target (spec 0010 AC-11).
 *
 * The value is percent decoded up to twice. It is kept only when the decoded
 * form is a same origin relative path: exactly one leading `/`, no `\`, no
 * control characters, no scheme, and not `/api`, `/login`, or `/register`
 * (or anything under them). Anything else becomes `/`.
 */
const FALLBACK = "/";
const BLOCKED = ["/api", "/login", "/register"];
const CONTROL = /[\u0000-\u001f\u007f]/;
const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const BASE = "http://next.invalid";

function decodeTwice(value: string): string | null {
  let current = value;
  for (let round = 0; round < 2; round += 1) {
    let next: string;
    try {
      next = decodeURIComponent(current);
    } catch {
      return null;
    }
    if (next === current) {
      break;
    }
    current = next;
  }
  return current;
}

export function safeNextPath(value: string | null | undefined): string {
  if (!value) {
    return FALLBACK;
  }
  const decoded = decodeTwice(value);
  if (decoded === null || SCHEME.test(decoded)) {
    return FALLBACK;
  }
  if (!decoded.startsWith("/") || decoded[1] === "/" || decoded[1] === "\\") {
    return FALLBACK;
  }
  if (decoded.includes("\\") || CONTROL.test(decoded)) {
    return FALLBACK;
  }
  // Resolve dot segments the way the browser will (`/./api` is `/api`).
  const url = new URL(decoded, BASE);
  if (url.origin !== BASE) {
    return FALLBACK;
  }
  const path = url.pathname.toLowerCase();
  if (BLOCKED.some((blocked) => path === blocked || path.startsWith(`${blocked}/`))) {
    return FALLBACK;
  }
  return value;
}
