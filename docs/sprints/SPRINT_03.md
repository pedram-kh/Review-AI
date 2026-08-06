# SPRINT 03 — Internal Dashboard + First Sends

> Length: 1 week · Status: ACTIVE (runs in parallel with Sprint 2's ⏸ external-gated tickets 2.4/2.5)
> Milestone (demo test): **Stakeholder sends the first 10–20 real outreach messages through the dashboard; every send and reply is tracked in the DB.**
> PM: Claude · Developer: Cursor
> Note: tickets 3.1–3.4 have NO dependency on 2.4/2.5. Ticket 3.5 (sending) requires 2.4/2.5 executed (queued messages exist).

## Rules for Cursor

1. All prior sprint rules apply. Read `/docs/LOGIC.md` §3 (status lifecycle) and §6 (outreach constraints) — the dashboard enforces them in UI and API.
2. This sprint spans TWO repos: `backend` (FastAPI, existing) and `app` (NEW Next.js repo). Keep docs in backend/docs as the single source; the app repo README links to them.
3. Never expose the backend admin API without auth. Never put the API key in client-side code — all data calls go through Next.js server routes.
4. When opening this sprint, append the Sprint 3 ticket table (bottom of this file) to `docs/PROGRESS.md`.

---

## Ticket 3.1 — Backend admin API

**Done when:** FastAPI exposes `/api/admin/*` endpoints protected by an `X-Admin-Key` header (constant-time compare against `ADMIN_API_KEY` env): `GET /api/admin/leads` (filters: status, channel, health_flag, search by name; sort: review_date asc/desc, created_at), `GET /api/admin/leads/{id}` (full lead + place + review), `PATCH /api/admin/leads/{id}` (editable: status, notes, generated_response, outreach_message, channel; stamps sent_at when status→sent, replied_at when →replied), `GET /api/admin/stats` (counts by status, sends today, sends per channel, replies). Status transitions validated against LOGIC §3 — illegal transitions → 422. Tests cover auth rejection, filters, transition validation, timestamp stamping.

**Cursor prompt:**
```
Read /docs/LOGIC.md §3 §6 and /docs/sprints/SPRINT_03.md. In the backend repo:
- app/routers/admin.py with the endpoints above; X-Admin-Key header auth (constant-time compare,
  ADMIN_API_KEY from env, 401 without it). Add ADMIN_API_KEY to .env.example + README env list.
- Status transition validation per LOGIC §3 exactly (only legal edges; 422 with clear message otherwise).
  sent requires a channel to be set. health-flagged leads (notes LIKE '%HEALTH_FLAG%') cannot enter
  'queued' or 'sent' unless the PATCH body includes confirm_health_reviewed=true (LOGIC §2/§6).
- Enable CORS restricted to the app's Netlify origin (env var APP_ORIGIN; default http://localhost:3000).
- pytest: auth 401, filter combos, illegal transition 422, health-flag guard, sent_at/replied_at stamping.
Update row 3.1 in /docs/PROGRESS.md.
```

## Ticket 3.2 — App repo bootstrap (Next.js + /admin basic auth)

**Done when:** new GitHub repo `reviewguide-app` (Next.js 14+, TypeScript, Tailwind, App Router) deploys on Netlify; `/` shows a placeholder; `/admin/*` is protected by HTTP Basic Auth via middleware (ADMIN_USER/ADMIN_PASS env); server-side API client calls the backend with X-Admin-Key (key lives ONLY in Netlify env, never shipped to browser); `/admin` renders live stats from `GET /api/admin/stats`.

**Stakeholder actions first:** create the empty GitHub repo `reviewguide-app`; create the Netlify site linked to it (I'll give click-steps when you're there).

**Cursor prompt:**
```
Create the Next.js app per SPRINT_03.md ticket 3.2 in a NEW project directory reviewguide-app:
- Next.js (App Router, TypeScript, Tailwind). Root page: minimal placeholder ("ReviewGuide").
- middleware.ts: HTTP Basic Auth for /admin/* using ADMIN_USER/ADMIN_PASS env vars.
- lib/api.ts: server-only fetch wrapper to BACKEND_URL with X-Admin-Key: ADMIN_API_KEY header.
  Data flows browser -> Next.js route handlers/server components -> FastAPI. The key must never
  appear in client bundles (verify: grep the build output).
- /admin page: stats cards from GET /api/admin/stats (leads by status, sent today, replies).
- netlify.toml + README (env vars: ADMIN_USER, ADMIN_PASS, BACKEND_URL, ADMIN_API_KEY; deploy steps).
- Push to the new repo; add a line to backend /docs/PROGRESS.md row 3.2 with the repo URL.
```

## Ticket 3.3 — Lead workspace UI

**Done when:** `/admin/leads` shows a filterable, sortable table (status, channel, health badge ⚠, restaurant, rating, review date, snippet; filters + sort per 3.1 API; Stakeholder picks leads manually — no forced order); `/admin/leads/[id]` shows: full review, generated response (editable textarea + Save), outreach message (editable + Save), contact links (FB / email / phone / website as buttons opening new tabs), actions: **Copy message** (clipboard), **Mark sent** (channel picker → PATCH status=sent), **Skip → dead**, notes field (autosaves). Health-flagged leads show a warning banner and require an explicit "reviewed by human" checkbox before Mark sent is enabled (maps to confirm_health_reviewed).

**Cursor prompt:**
```
Build /admin/leads (list) and /admin/leads/[id] (detail) per SPRINT_03.md ticket 3.3, against the
3.1 API via lib/api.ts. Keep UI plain Tailwind, function over beauty. Requirements:
- List: filters (status, channel, health), sort toggle (review date desc default), search box; row
  click -> detail. Health rows show ⚠ badge.
- Detail: review (read-only), generated_response + outreach_message editable with Save (PATCH),
  contact buttons (fb_url, mailto:email, tel:phone, website), Copy message button (copies
  outreach_message), Mark sent (channel select prefilled from lead.channel), Skip (status=dead,
  requires a note), notes autosave.
- Health-flagged: yellow banner + "I reviewed this response" checkbox gating Mark sent
  (sends confirm_health_reviewed=true).
- After Mark sent: toast + return to list (filtered as before).
Update backend /docs/PROGRESS.md row 3.3.
```

## Ticket 3.4 — Send-day guardrails + tracking

**Done when:** the dashboard shows "sent today: N/20" (LOGIC §6 cap); at N=20 Mark sent is disabled with a message (API also rejects >20/day with 429); a Replies view (`/admin/replies`) lists leads in status=sent with quick actions: Mark replied / Mark converted / Mark dead; stats page shows reply-rate % (replied/sent) — the G2 gate number.

**Cursor prompt:**
```
Per SPRINT_03.md ticket 3.4:
- Backend: GET /api/admin/stats includes sent_today and reply_rate; PATCH to status=sent returns 429
  when 20 sends already today (Europe/Warsaw timezone day boundary). Test both.
- App: sends-today counter in /admin header (N/20, red at 20, Mark sent disabled); /admin/replies
  page listing status=sent leads (sorted by sent_at desc) with one-click Mark replied / converted /
  dead (dead requires note); reply_rate % on the stats page labeled "G2 gate metric".
Update /docs/PROGRESS.md row 3.4.
```

## Ticket 3.5 — First real sends (sprint milestone — REQUIRES 2.4/2.5 executed)

**Done when:** 2.4/2.5 have run (leads queued with final messages); Stakeholder has sent 10–20 real messages via the dashboard over 1–2 days (Facebook priority, manual pick); every send is status=sent with correct channel + sent_at; any replies tracked. A short SENDING_LOG section in PROGRESS.md records: date, sends, channel split, replies so far.

**Cursor prompt (run only after PM confirms 2.4/2.5 executed):**
```
Verify readiness for first sends: count of status=queued leads, channel split, spot-check 3 queued
outreach_messages render complete (no empty placeholders). Add a SENDING_LOG section to
/docs/PROGRESS.md (table: date | sends | fb/email/form split | replies | notes). Then hand over to
the Stakeholder — sending is human-only per LOGIC §6. Update row 3.5 when the Stakeholder confirms
the first 10+ sends are logged.
```

---

## Sprint 3 PROGRESS.md rows (Cursor: append when opening the sprint)

```
## Current sprint: SPRINT 3 — Internal Dashboard + First Sends (parallel with Sprint 2 ⏸ tickets)

| # | Ticket | Status | Files touched | Cursor notes | PM verdict |
|---|---|---|---|---|---|
| 3.1 | Backend admin API | ⬜ | | | |
| 3.2 | App repo bootstrap (/admin basic auth) | ⬜ | | | |
| 3.3 | Lead workspace UI | ⬜ | | | |
| 3.4 | Send-day guardrails + tracking | ⬜ | | | |
| 3.5 | First real sends (milestone; needs 2.4/2.5) | ⬜ | | | |

### Sprint 3 blockers
- 3.5 blocked until Sprint 2 tickets 2.4/2.5 execute (external: PL reviewer verdict + template approval)

### Sprint 3 open questions for Stakeholder
- Create GitHub repo `reviewguide-app` + Netlify site (blocks 3.2 deploy)
- Choose ADMIN_USER/ADMIN_PASS (basic auth) — put in Netlify env, never in chat/repo
```

## Sprint 3 review checklist (PM)

- [ ] Admin API: 401 without key; key absent from app client bundle (grep build output)
- [ ] Status transitions: illegal edges rejected (spot-test via API)
- [ ] Health-flag guard: cannot Mark sent without human-review confirmation (UI + API)
- [ ] 20/day cap enforced in API (not just UI)
- [ ] Milestone: 10+ real sends logged with correct channel + sent_at; SENDING_LOG exists
- [ ] Reply-rate metric visible (G2 gate number)
