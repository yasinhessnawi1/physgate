import type { Result } from "../../api/client";
import type { RunEvent } from "../../api/events";

export const FOLLOW_EVERY_MS = 5_000;

export interface FollowedRead {
  readonly result: Result<readonly RunEvent[]> | null;
  readonly route: string | null;
  readonly again: () => void;
  readonly failedAgain: boolean;
}

export function useFollowedLog(base: string | null, going: boolean): FollowedRead {
  void base;
  void going;
  return { result: null, route: null, again: () => undefined, failedAgain: false };
}
