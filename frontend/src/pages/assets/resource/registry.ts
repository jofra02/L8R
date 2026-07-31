import type { ResourceAdapter } from "./types";

/* eslint-disable @typescript-eslint/no-explicit-any -- the registry is
 * heterogeneous by design; each adapter is type-safe internally. */
const adapters = new Map<string, ResourceAdapter<any>>();

export function registerAdapter(adapter: ResourceAdapter<any>): void {
  adapters.set(adapter.type, adapter);
}

export function getAdapter(type: string): ResourceAdapter<any> | undefined {
  return adapters.get(type);
}
