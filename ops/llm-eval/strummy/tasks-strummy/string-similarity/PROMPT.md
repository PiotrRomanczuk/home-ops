Reimplement `calculateSimilarity(str1: string, str2: string): number` in
`lib/utils/string-similarity.ts` so that every test in
`lib/utils/__tests__/string-similarity.test.ts` passes.

Behaviour:
- Returns a similarity score from 0 (completely different) to 100 (identical
  after normalization).
- Normalize each input by lowercasing, trimming, and removing every character
  that is not a word character or whitespace, before comparing.
- Normalized-equal strings (including empty-vs-empty) score exactly 100.
- Empty vs non-empty scores 0.
- Otherwise use Levenshtein edit distance: score = round((maxLen - distance) / maxLen * 100).

Only edit `lib/utils/string-similarity.ts`. Do not edit the test file.
