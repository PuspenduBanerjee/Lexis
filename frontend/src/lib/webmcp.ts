// Thin wrapper around the WebMCP browser API (`document.modelContext`) - lets an
// in-page AI agent discover and call tools this app registers, the same way an
// MCP client calls tools over `/api/mcp` (see `lexis_api/routers/mcp.py`), just
// without a separate connection. No browser ships this unflagged yet, so
// `@mcp-b/webmcp-polyfill` fills it in (a no-op once real support lands).
// `@mcp-b/webmcp-types` is types-only (its `exports` field publishes no runtime
// entry point) - a triple-slash reference pulls in its `declare global` block
// (`Document.modelContext`) for the type checker without ever becoming a real
// import a bundler would try to resolve at build time.
/// <reference types="@mcp-b/webmcp-types" />
import { initializeWebMCPPolyfill } from "@mcp-b/webmcp-polyfill";
import { useEffect } from "react";

initializeWebMCPPolyfill();

type MaybePromise<T> = T | Promise<T>;

export interface WebMcpTool {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
    additionalProperties?: boolean;
  };
  execute: (input: Record<string, unknown>) => MaybePromise<unknown>;
}

// The real `document.modelContext.registerTool` type is a set of overloaded
// generics keyed to a schema literal (see `@mcp-b/webmcp-types`), meant for call
// sites that inline one tool's schema so TS can infer `execute`'s argument type
// from it. Our tools are built dynamically (one per metric/model), so that
// inference is neither possible nor useful - this narrower shape is what every
// WebMCP runtime actually accepts on the wire, and is all this app needs.
interface SimpleModelContext {
  registerTool(tool: WebMcpTool, options?: { signal?: AbortSignal }): Promise<void>;
}

/** Registers `tools` on `document.modelContext` for as long as the calling
 * component stays mounted, and unregisters them on unmount or before the next
 * re-registration. No-ops when the document has no `modelContext` at all
 * (shouldn't happen given `initializeWebMCPPolyfill()` above, but stays safe if
 * a host page ever removes it). Callers must memoize `tools` (e.g. `useMemo`) -
 * a new array identity re-registers every render. */
export function useWebMcpTools(tools: WebMcpTool[]): void {
  useEffect(() => {
    const modelContext = document.modelContext as unknown as SimpleModelContext | undefined;
    if (!modelContext) return;
    const controller = new AbortController();
    for (const tool of tools) {
      modelContext.registerTool(tool, { signal: controller.signal }).catch((err: unknown) => {
        // Our own cleanup below aborts `controller.signal` on unmount/dep-change,
        // which can race a still-pending `registerTool()` call (React StrictMode's
        // double-invoke does this on every mount in dev) - that rejection is
        // expected, not a real failure, so only log anything else.
        if (controller.signal.aborted) return;
        console.error(`webmcp: failed to register tool "${tool.name}"`, err);
      });
    }
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when the tool list itself changes
  }, [tools]);
}
