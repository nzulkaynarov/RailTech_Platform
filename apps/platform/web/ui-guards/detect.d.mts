export interface Hit {
  kind: string;
  line: number;
  column: number;
  selector?: string;
}
export interface AllowEntry {
  path: string;
  count: number;
  reason: string;
}
export const WEB_ROOT: string;
export const GUARDED_DIRS: string[];
export const KINDS: Record<string, string>;
export const CSS_KIND: string;
export const CSS_MESSAGE: string;
export const ALL_KINDS: string[];
export function detectTs(source: string, fileName?: string): Hit[];
export function detectCss(source: string): Hit[];
export function webPath(absolute: string): string;
export function isGuardedTs(path: string): boolean;
export function isGuardedCss(path: string): boolean;
export function scanTree(): Map<string, Map<string, number>>;
export function loadAllowlist(): Record<string, AllowEntry[]>;
export function loadBaseline(): Record<string, number>;
