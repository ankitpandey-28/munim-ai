# Munim AI — Frontend

Next.js (App Router) + React + TypeScript + Tailwind CSS. See the root [README](../README.md) and [docs/architecture.md](../docs/architecture.md).

## Run locally

```bash
cp .env.example .env.local   # PowerShell: Copy-Item .env.example .env.local
npm install
npm run dev                  # http://localhost:3000
```

| Script | Purpose |
|---|---|
| `npm run dev` | Development server |
| `npm run lint` | ESLint |
| `npm run build` | Production build (includes type checking) |
| `npm start` | Serve the production build |

## Structure

```
src/
├── app/
│   ├── page.tsx              # Landing
│   ├── (auth)/login, register
│   └── (app)/dashboard, assistant, sales, inventory, customers,
│            udhaar, expenses, reports, suppliers, settings
├── components/               # Shared UI
└── lib/                      # Navigation metadata, helpers
```

All routes are placeholders in Phase 2.1.

## API access

The browser never calls FastAPI directly. `next.config.ts` rewrites `/api/v1/*` to `BACKEND_INTERNAL_URL` (same-origin proxy, ADR-17). For example, `http://localhost:3000/api/v1/health` reaches the backend health endpoint.
