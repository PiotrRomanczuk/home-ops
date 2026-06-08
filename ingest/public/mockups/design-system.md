# home-ops UI Design System

## Typography
- **Primary Font**: `JetBrains Mono`, fallback to `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`.
- **Numerals**: `font-variant-numeric: tabular-nums;` used everywhere, particularly crucial for timestamps and durations to ensure stable columns.
- **Sizes**:
  - Base: `13px` (Desktop), `12px` (Mobile) to ensure high density.
  - Line Height: `1.4` (compact but readable).
- **Headers**: Small-caps styling (`font-variant: small-caps; letter-spacing: 0.05em; font-size: 11px; text-transform: uppercase; color: var(--fg-muted)`) to differentiate from data rows without adding visual weight.

## Color Tokens (Dark Theme)
```css
:root {
  --bg: #0e1116; /* Base dark background */
  --bg-elevated: #161b22; /* Slightly lighter for hovering/drawers */
  --bg-selected: #1f2937; /* Selected row or active element */
  --bg-input: #010409;
  
  --border: #30363d;
  --border-focus: #58a6ff;
  
  --fg: #d0d7de; /* Main text */
  --fg-muted: #8b949e; /* Unimportant data, timestamps, headers */
  
  --accent: #58a6ff; /* Links, active states, focus */
  
  /* Log Levels */
  --lvl-debug: #8b949e;
  --lvl-info: #58a6ff;
  --lvl-warn: #d29922;
  --lvl-error: #f85149;
  --lvl-fatal: #ff7b72;

  /* Status Footer */
  --status-good: #3fb950;
  --status-warn: #d29922;
  --status-stale: #f85149;
}
```

## Interaction Model
- **Keyboard-first**: 
  - `/` focuses the search/filter input.
  - `p` or `space` pauses/resumes the live tail.
  - `1-5` sets the minimum log level (1=debug, 5=fatal).
  - `j`/`k` (Vim bindings) or `Up`/`Down` arrows to navigate selected row up and down.
  - `Enter` or `Right Arrow` to expand the inline detail view of the selected row.
- **Hover**: Rows highlight slightly (`--bg-elevated`) on hover. Actionable elements (chips, links) change to `--accent` on hover.
- **Detail View**: Expand-inline (accordion style). Clicking a row pushes subsequent rows down and reveals the formatted JSON `data` payload.
- **Correlation Chips**: Within the expanded JSON payload, keys like `pid`, `request_id`, `trace_id` are styled as chips. Clicking one instantly appends `key=value` to the implicit AND scratch filter input.

## Empty / Loading / Error States
- **Empty State (No logs match filter)**: A single row displaying `[No matching events found]` in `--fg-muted`. No large illustrations or cards.
- **Loading / Reconnecting State**: A subtle `--accent` colored pulse indicator next to the "Live Tail" toggle. If the API is unreachable, the status footer changes to `--status-stale` with text `Ingest API: UNREACHABLE`.
- **Error State**: Rendered as a standard log row with `level=fatal` originating from `agent:ui-client`.
