# Deploying the API to Vercel

The API ships as a **Vercel container function**: Vercel builds `backend/Dockerfile.vercel` and runs it in `sin1` (Singapore, next to the Neon database). The Python runtime is not used because it caps a function at 500 MB and this backend is about 1.1 GB (torch for the Malay name model, spaCy, Presidio).

## Project settings

| Setting | Value |
| :--- | :--- |
| Repository | this one, branch `main` |
| Root directory | `backend` |
| Framework preset | Container |
| Function region | `sin1` |
| Max duration | 300 s (an analysis run is one request) |

The first build installs about 1.1 GB of packages and downloads the Malay model into the image (about 2 minutes). Later builds reuse cached layers when `requirements.txt` has not changed.

## Environment variables

Set these in the Vercel project (Production). Values live in your own `.env`; never commit them.

| Variable | Purpose |
| :--- | :--- |
| `DATABASE_URL` | Neon connection string for the **non-owner** role `synapsed_app` (row-level security applies to it) |
| `NEON_AUTH_BASE_URL` | Neon Auth base URL (used to verify sign-in tokens) |
| `NEON_STORAGE_ENDPOINT`, `NEON_STORAGE_REGION`, `NEON_STORAGE_ACCESS_KEY`, `NEON_STORAGE_SECRET_KEY`, `NEON_STORAGE_BUCKET` | Neon Object Storage |
| `GROQ_API_KEY`, `GOOGLE_API_KEY`, `SEALION_API_KEY` | Model providers |
| `FRONTEND_ORIGIN` | The deployed frontend's origin(s), for CORS: no trailing slash, several separated by commas (the project's short and long Vercel addresses both work) |
| `JIRA_*` | Optional; the Jira button is hidden when they are blank |

**Do not set `DATABASE_URL_ADMIN`.** It is the database owner's connection string, used only for migrations and tests. The server never needs it, and a leaked owner credential bypasses row-level security.

Model names, provider order, upload size and rate limits have working defaults (see `backend/.env.example`); set them only to change them.

## After the first deploy

1. `GET /health` should answer `{"status": "healthy", "database": true}`. A `503` with `"database": false` means `DATABASE_URL` is missing or wrong.
2. Add the frontend's URL to the Neon Auth trusted domains, and turn off "Allow Localhost" there.
3. Narrow the storage bucket's CORS rule from `*` to the frontend origin (browsers upload files straight to storage with presigned URLs).
4. Delete any throwaway test project.

## Limits to know about (Vercel Hobby)

- 2 GB memory and 1 vCPU per function; this API uses about 0.65 GB with both name models loaded.
- 300 s per request, which is why analysis runs in batches (`ANALYZE_BATCH_SIZE`) and streams its progress.
- 4.5 MB request bodies, which is why uploads go straight to storage.
- Instances scale to zero when idle. The first request after a pause starts a new instance (about 10 s); the name models load in the background so `/health` answers immediately.
- Hobby is for personal, non-commercial use.
