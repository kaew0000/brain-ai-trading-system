# MIGRATION — feat(world-performance-v1)

## Backend Integration (Claude)

### MockDataProvider → Real Data
**File**: `dashboard_src/src/components/mock/MockDataProvider.tsx`

When portfolio REST / WS endpoints are ready:

1. Create a real data hook (e.g. `usePortfolioData`) that calls `/api/portfolio`.
2. Replace `<MockPortfolioProvider>` in `pages/Portfolio.tsx` with the real
   provider.
3. `PortfolioDashboard.tsx` is pure presentational and requires no changes if
   the data shape matches.

### Store Equality
No backend changes required. Equality guards are frontend-only and reduce
re-render frequency.

## Frontend

### New Dependencies
None. All changes use existing dependencies:
- React 18, Phaser 3.60, Zustand 4.5, Framer Motion 11, Tailwind 3.4

### New Routes
- `/world` — World HQ (Phaser canvas). Lazy-loaded; chunk downloaded on first
  visit.

### New Files
| File | Purpose |
|------|---------|
| `src/hooks/useThrottle.ts` | Throttle hook for performance |
| `src/hooks/useDebounce.ts` | Debounce hook for inputs |
| `src/components/mock/MockDataProvider.tsx` | Mock data adapter for Portfolio |
| `src/components/common/PageLoader.tsx` | Suspense fallback UI |
| `src/pages/portfolio/PortfolioDashboard.tsx` | New portfolio UI |
| `src/pages/world/assets/AssetPipeline.ts` | Asset preloader utility |

### Modified Files
| File | Change |
|------|--------|
| `src/App.tsx` | React.lazy code splitting, added `/world` route |
| `src/main.tsx` | Added global ErrorBoundary |
| `src/stores/index.ts` | Shallow equality guards on all stores |
| `src/components/layout/Layout.tsx` | Accessibility roles, version bump |
| `src/components/common/index.tsx` | Added `PageLoader` and `Skeleton` exports |
| `src/pages/Portfolio.tsx` | Wraps `PortfolioDashboard` in `MockPortfolioProvider` |
| `src/pages/world/WorldPage.tsx` | Memo, throttle, named listener cleanup |
| `src/pages/world/components/Minimap.tsx` | Offscreen canvas, hover labels, blur overlay |
| `vite.config.ts` | Additional manual chunks |

## Rollback
If issues occur, revert to previous commit on `main`. No database or backend
schema changes were made.
