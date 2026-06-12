# Frontend Guide

Frontend code lives in `frontend/src/`.

## Commands

Run commands from `frontend/`:

```bash
npm install
npm run dev
npm run build
npm run typecheck
npm run lint
```

The Vite dev server uses port `5173` and proxies `/api` to the backend.

## Structure

- API client code: `src/api/`.
- Reusable components: `src/components/`.
- Hooks: `src/hooks/`.
- Pages/routes: `src/pages/`.
- Shared types: `src/types/`.

## Frontend Rules

- Follow the existing React 18, Vite, TypeScript, and TailwindCSS patterns.
- Keep operational screens dense, scannable, and work-focused.
- Use existing API client and hook patterns before adding new data-fetching abstractions.
- For UI changes, verify with `npm run typecheck` and `npm run build` at minimum; run `npm run lint` when touching lint-sensitive code.
- Do not edit generated `frontend/dist/` output.
