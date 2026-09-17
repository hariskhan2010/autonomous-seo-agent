# Remaining keys — pick up here

Everything else from this build session is done and verified (dashboard, real LLM roles, backend
fixes — see `CLAUDE.md`). These are the only things left, and only you can get them. Full
reference for the whole project's keys is `NEEDED-KEYS.md`; this file is just today's short list.

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

## 2. SerpAPI (real search-results data — free to start)

1. **serpapi.com** → **Sign up** (free tier: 100 searches/month, no credit card needed)
2. Your API key is shown on the account dashboard right after signup
3. Paste it into `.env`:
   ```
   SERPAPI_API_KEY=...
   ```
   *(Alternative: DataForSEO — dataforseo.com, pay-as-you-go from ~$25, needs a card. SerpAPI's
   free tier is the easier no-card starting point.)*

## 3. GitHub token (so the agent can open real PRs)

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
same as I did for the Gemini/OpenRouter/Zhipu/Google OAuth keys already in `.env`.

## Two other open items (not credentials)

- **Disk space on C:** still at 0 bytes free from earlier — blocks running Temporal locally.
  Windows Settings → System → Storage is the reliable way to find what's using it.
- **Git commit**: 254+ files in this project have never been committed. Say the word whenever
  you want that done — it's a deliberate hold, not something blocked on you technically.
