/**
 * Every `(app)` page calls `requireSession` first (spec 0011 child 0001 AC-13).
 * Reads the source with the TypeScript compiler, so a new page can't skip the
 * guard: `requireSession` must be the first awaited call in the default export,
 * ignoring awaits of `params` and `searchParams`, and come before any data call.
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const APP_DIR = path.join(__dirname, "../../src/app/(app)");

function pageFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return pageFiles(full);
    }
    return entry.name === "page.tsx" ? [full] : [];
  });
}

function defaultExport(source: ts.SourceFile): ts.FunctionDeclaration | null {
  for (const statement of source.statements) {
    if (
      ts.isFunctionDeclaration(statement) &&
      statement.modifiers?.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword)
    ) {
      return statement;
    }
  }
  return null;
}

const ALLOWED_BEFORE_GUARD = new Set(["params", "searchParams"]);

/** The reason a page's source is unguarded, or `null` when it is guarded. */
export function guardProblem(text: string): string | null {
  const source = ts.createSourceFile(
    "page.tsx",
    text,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const page = defaultExport(source);
  if (!page?.body) {
    return "no default export function";
  }
  const calls: ts.Node[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isAwaitExpression(node)) {
      calls.push(node.expression);
    }
    if (ts.isCallExpression(node) && !isAwaited(node)) {
      calls.push(node);
    }
    ts.forEachChild(node, visit);
  };
  const isAwaited = (node: ts.Node) => ts.isAwaitExpression(node.parent);
  visit(page.body);

  for (const call of calls) {
    if (ts.isIdentifier(call) && ALLOWED_BEFORE_GUARD.has(call.text)) {
      continue;
    }
    if (ts.isCallExpression(call) && ts.isIdentifier(call.expression)) {
      if (call.expression.text === "requireSession") {
        return ts.isAwaitExpression(call.parent) ? null : "requireSession is not awaited";
      }
      // Building a string or the path from params is not a data call.
    }
    return `${call.getText()} runs before requireSession`;
  }
  return "requireSession is never awaited";
}

const pages = pageFiles(APP_DIR);

describe("the (app) session guard", () => {
  it("finds the pages", () => {
    expect(pages.length).toBeGreaterThanOrEqual(3);
  });

  it.each(pages.map((file) => [path.relative(APP_DIR, file), file]))("%s", (_name, file) => {
    expect(guardProblem(readFileSync(file, "utf8"))).toBeNull();
  });

  it("fails a scratch page with no guard", () => {
    const text = `
      export default async function Page({ params }) {
        const { id } = await params;
        const data = await load(id);
        return data;
      }`;
    expect(guardProblem(text)).toContain("load(id) runs before requireSession");
  });

  it("fails a page that loads data first", () => {
    const text = `
      export default async function Page({ searchParams }) {
        const query = await searchParams;
        const server = await serverRequestInit();
        const session = await requireSession("/", query);
        return session;
      }`;
    expect(guardProblem(text)).toContain("serverRequestInit() runs before requireSession");
  });

  it("fails a guard that isn't awaited", () => {
    const text = `
      export default async function Page() {
        requireSession("/");
        return null;
      }`;
    expect(guardProblem(text)).not.toBeNull();
  });

  it("passes a guard after params and searchParams", () => {
    const text = `
      export default async function Page({ params, searchParams }) {
        const { id } = await params;
        const query = await searchParams;
        const session = await requireSession(\`/x/\${id}\`, query);
        return session;
      }`;
    expect(guardProblem(text)).toBeNull();
  });
});
