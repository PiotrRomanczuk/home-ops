export type Level = 'debug' | 'info' | 'warn' | 'error' | 'fatal';

export const LEVELS: Level[] = ['debug', 'info', 'warn', 'error', 'fatal'];
export const LEVEL_RANK: Record<Level, number> = { debug: 0, info: 1, warn: 2, error: 3, fatal: 4 };
