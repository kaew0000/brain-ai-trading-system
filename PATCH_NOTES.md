# PATCH NOTES — feat(world-performance-v1)

## Summary
Frontend performance and UX pass for Brain Bot V16 Dashboard. Introduces React.lazy
code-splitting, Zustand store equality guards, World HQ Minimap v2, and a new
Portfolio Dashboard backed by MockDataProvider adapters.

## Changes

### Architecture
- **Code Splitting**: All routes converted to `React.lazy()` with `<Suspense>`
  fallback (`PageLoader`). Initial bundle no longer eagerly loads every page.
- **Error Boundary**: Global `ErrorBoundary` in `main.tsx` prevents white-screen
  crashes and offers a branded recovery UI.
- **Store Equality**: All Zustand stores now use shallow / semantic equality
  guards, eliminating re-render storms caused by 1 Hz WS heartbeats with
  unchanged payloads.

### World HQ
- **WorldPage**: Wrapped in `React.memo`; NPC position updates throttled to
  200 ms; event listeners use named `off()` cleanup instead of
  `removeAllListeners()`.
- **Minimap v2**: Offscreen canvas caches static terrain; room label tooltips on
  hover; CSS `backdrop-blur` overlay; `willReadFrequently` canvas hint.
- **Asset Pipeline**: New `AssetPipeline.ts` utility for priority-based asset
  preloading (critical / deferred / on-demand).

### Portfolio Dashboard
- **MockDataProvider**: `MockPortfolioProvider` delivers realistic mock portfolio
  data wrapped for easy backend replacement by Claude.
- **PortfolioDashboard**: Allocation bars with target-drift indicators, SVG equity
  sparkline, performance metric cards (Sharpe, Max DD, Win Rate, Profit
  Factor), animated position list.

### UI / UX
- **Layout**: Accessibility roles (`navigation`, `menubar`), version bumped to V16.
- **Responsive**: Portfolio uses 12-column grid that collapses gracefully on
  mobile.
- **Tailwind**: Zero new design tokens; all changes use existing color palette.

### Build
- **Vite chunking**: Added `ui-vendor` and `animation-vendor` manual chunks for
  better HTTP cache hit ratios.
