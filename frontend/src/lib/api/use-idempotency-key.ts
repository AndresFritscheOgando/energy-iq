"use client";

import { useRef } from "react";

/**
 * One key per submission (spec 0011). The same submission retried, including
 * "Save anyway", reuses its key, so the API replays instead of writing twice.
 * Changed values make a new key, and so does `reset()` after success.
 *
 * The generated client has no idempotency parameter, so forms pass the key per
 * call: `{ headers: { "Idempotency-Key": key } }`.
 */
export function useIdempotencyKey() {
  const current = useRef<{ fingerprint: string; key: string } | null>(null);
  return {
    keyFor(fingerprint: string): string {
      if (current.current?.fingerprint !== fingerprint) {
        current.current = { fingerprint, key: crypto.randomUUID() };
      }
      return current.current.key;
    },
    reset() {
      current.current = null;
    },
  };
}
