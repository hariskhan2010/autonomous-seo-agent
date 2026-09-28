# Remaining keys — pick up here

Everything else from the build session is done and verified (dashboard, real LLM roles, backend
fixes — see `CLAUDE.md`). These are the only things left, and only you can get them. Full
reference for the whole project's keys is `NEEDED-KEYS.md`; this file is just the short list.

**Update (2026-09-18):** SerpAPI is done — `SERPAPI_API_KEY` is set in `.env` and verified with a
real search call (`status: Success`). Two keys left below. Disk space and the git commit (both
previously listed as open items) are also resolved — see the bottom of this file.

---

## 1. PageSpeed + CrUX (same Google Cloud project you already made — 2 minutes)

You already created a project in Google Cloud Console for the OAuth client. Reuse it:

1. **console.cloud.google.com** → make sure that same project is selected (top-left dropdown)
2. Search bar → **"PageSpeed Insights API"** → open it → **Enable**
3. Search bar → **"Chrome UX Report API"** → open it → **Enable**
4. **APIs & Services → Credentials** → reuse an existing API key, or **Create Credentials → API key**
5. Paste that one key into **both** lines in `.env`:
   ```
   PAGESPEED_API_KEY=...
   CRUX_API_KEY=...
   ```

## 2. GitHub token (so the agent can open real PRs)

1. **github.com** → your avatar → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**
2. Name it, set **Repository access** to the specific repo you want it working against
3. **Permissions → Repository permissions**: set **Contents** → Read and write, **Pull requests**
   → Read and write
4. Generate → paste into `.env`:
   ```
   GITHUB_TOKEN=...
   ```

---

## After you've added these

Just tell me — I'll verify each one with a real API call (not just check the field isn't empty),
same as I did for the Gemini/OpenRouter/Zhipu/Google OAuth/SerpAPI keys already in `.env`.

## Resolved (no longer open)

- ~~SerpAPI key~~ — set and verified 2026-09-17.
- ~~Disk space on C:~~ — was 0 bytes free, now 7.8G free; no longer blocks Docker/Temporal locally.
- ~~Git commit~~ — the 254+ never-committed files are now in git (`bf1b30d`, initial commit,
  307 files). `.env` and other secrets confirmed gitignored before committing.

## Known issue (separate from credentials)

Local Temporal (`docker compose -f infra/docker-compose.yml up -d db redis minio temporal
temporal-ui`) still doesn't come up: `db`/`redis`/`minio` start fine, but the
`temporalio/auto-setup:1.24.2` container crashes on startup (exit code 2, corrupted/unreadable
output instead of a normal error) — reproduced across container recreation and a fresh image pull,
so it's not a caching fluke. Postgres itself logs nothing wrong. Not yet root-caused — options to
try next: swap the local Postgres image (`pgvector/pgvector:pg16` → plain `postgres:16`) for the
temporal databases, or use Temporal Cloud instead of running it locally.
