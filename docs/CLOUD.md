# Free cloud demo: Render + Neon

The deployment uses one Render **Free** Docker web service and a Neon **Free** PostgreSQL project. It runs independently of a local computer. All portals share one HTTPS origin.

## Runtime

`deploy/render.Dockerfile` builds the React frontend, installs the locked Python dependencies, and includes the official Caddy and Mailpit binaries. `deploy/render-entrypoint.py` applies migrations and supervises four processes:

- Caddy serves the built frontend and proxies `/api/*` to the API.
- Uvicorn runs the API on container-local port 8000.
- The existing durable worker processes authorized analyses and approved email outbox records.
- Mailpit captures email on container-local SMTP port 1025.

Only Caddy's `PORT` is public. The database connection and Gemini key are runtime environment secrets. The default UI accounts remain fictional demo fixtures, so `APP_ENV=development` and `DEMO_MODE=true` are intentional for this presentation deployment. This is not a deployment for real HR personal data.

`/mailbox/` is a read-only preview inbox protected by the app's staff session. Sign in through `/hr/login` before opening it. The API docs also require a staff session. The front end, API, session cookies and CSRF checks use the same origin; secure cookies are enabled.

## Persistence

Render Free has no durable local disk. The runtime enables `DATABASE_FILE_STORAGE=true`, which stores the original PDF bytes in PostgreSQL alongside the existing document metadata. Downloads restore a missing local cache file only after ownership checks, and verify the saved size and SHA-256 digest. The bytes are deferred from ordinary database queries and never included in candidate list JSON.

The local preview inbox is reconstructed on startup from already-sent, approved outbox payloads. No external delivery occurs, and no approval or delivery status is changed. Restored messages carry `X-Demo-Restored: true`. Historical email bodies retain their original approved links; newly prepared drafts use the cloud origin.

## Setup

`render.yaml` declares the free service. Use Frankfurt for both the Render service and Neon database. Set the following environment values in Render:

- `DATABASE_URL`: the Neon PostgreSQL connection string with TLS required.
- `SESSION_SECRET`: a persistent, random secret of at least 32 characters.
- `GEMINI_API_KEY`: server-side only.
- `APP_ENV=development`, `DEMO_MODE=true`.
- `AI_MODE=live`, `GEMINI_MODEL=gemini-3.6-flash`.
- Keep `AI_CONCURRENCY=1`, `AI_RPM=5`, `AI_DAILY_CALL_BUDGET=40` for the small demo instance.

The launcher obtains the HTTPS origin from `RENDER_EXTERNAL_URL`, derives the public mailbox address, and normalizes the Neon connection string for psycopg. It never seeds, resets, or recreates existing demo records on startup. Import the existing database and CV bytes before the initial deployment.

Staff passwords for a shared cloud demo should differ from the public fixture credentials documented in this repository. The local database can keep its original passwords.

## Before presenting

Open `/jobs` and `/hr/dashboard` a few minutes before the presentation, complete a real sign-in, and open the candidate slot picker. Check that the service is live and the worker has started. Keep the presentation tab open while interacting with the app.

Render Free sleeps after 15 minutes without inbound traffic and can take about one minute to wake. An idle free service is not an always-on hosting guarantee. Neon also has free compute, storage and transfer quotas. Do not add paid resources to remove these limits without explicit approval.

Auto-deploy is off in the provided configuration so unrelated pushes do not replace the competition build. Redeploy deliberately after testing a change. The entrypoint exits if a child process dies, allowing the platform to restart the entire service. Database records and CV bytes remain in Neon across those restarts.

Free plan references: https://render.com/docs/free and https://neon.com/docs/introduction/plans.
