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

## Local Temporal — replaced (2026-09-29)

The `temporalio/auto-setup:1.24.2` container used to crash on startup (exit code 2, garbled
output). That image is deprecated upstream, so it's gone: `temporal` in `infra/docker-compose.yml`
now runs the Temporal CLI dev server (`server start-dev`, SQLite, UI on http://localhost:8080) and
no longer touches the app's Postgres. Two ways to run it:
- `make up-temporal` (Docker), or
- `make temporal-dev` — no Docker at all, needs the Temporal CLI installed.

Verified: all 5 `SeoAgentWorkflow` tests pass against a real dev server
(`WorkflowEnvironment.start_local()`). Not yet verified: the Docker image path itself (Docker
Desktop was off). If Docker containers crash with garbled output again, check free space on C: —
Docker Desktop's disk lives there and it was down to ~3 GB.
