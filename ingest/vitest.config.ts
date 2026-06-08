import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/__tests__/**/*.test.ts', 'public/__tests__/**/*.test.mjs'],
    testTimeout: 10_000,
    hookTimeout: 15_000,
    // Each test file gets its own worker so DB state in jobs-state-machine
    // doesn't leak across files.
    pool: 'forks',
    poolOptions: { forks: { singleFork: false } },
  },
});
