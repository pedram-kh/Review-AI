# SPRINT 06 — Video + Polish + Iterate

> Length: 1 week (planned) · Status: OPENED BY CR-1 (full PM+Stakeholder scoping session still
> pending — see ROADMAP.md §3 sprint plan). CR-1 landed ahead of that session because it's a
> Stakeholder-decided, self-contained change with its own compliance deadline (card-network
> pre-charge reminder rules), not scope that needed sprint planning to shape.
> PM: Claude · Developer: Cursor.

## Rules for Cursor

All prior rules apply unchanged (see SPRINT_05.md's Rules for Cursor and LOGIC.md in full).

---

## CR-1 — Trial payment model: cardless → card-upfront

**Origin:** Stakeholder decision, 2026-08-09, logged in `docs/ROADMAP.md`'s decisions log —
overrides the PM's original cardless-launch recommendation (and the day-11-nudge middle path) in
favor of UX continuity (no second action needed to convert) and guaranteed auto-conversion at day
14. Sprint 5 was already closed when this landed, so it opens Sprint 6 as a change request rather
than a numbered ticket in the closed sprint.

**Scope, as specified:**
1. `POST /api/billing/checkout`: `payment_method_collection` `"if_required"` → `"always"`.
   `trial_period_days=14` unchanged. `subscription_data.trial_settings.end_behavior` was never
   configured in this codebase (confirmed by repo-wide search) — nothing to remove/adjust there.
2. Card-network compliance: trials that auto-charge require a pre-charge reminder to the
   cardholder. Stripe's own reminder mechanism is dashboard-only, not API-configurable (confirmed
   against current Stripe docs) — see the PROGRESS.md row for the exact toggle path handed to the
   Stakeholder.
3. `reviewguide-marketing`: remove "bez karty" everywhere (hero/meta description, pricing card,
   FAQ); new copy direction "14 dni za darmo · anuluj w każdej chwili · pierwsza płatność dopiero
   po okresie próbnym"; FAQ answer rewritten honestly. Redeploy.
4. `reviewguide-app` `/app`: audited for "bez karty"/trial copy — none exists to update; checkout
   button copy ("Rozpocznij okres próbny") stays as instructed.
5. Live-verify in Stripe test mode against the real deployed backend: checkout requires a card,
   subscription lands trialing with a `default_payment_method`, portal cancel works.
6. Doc-parity, full suite green, PM report.

**Full evidence:** see the CR-1 row in `docs/PROGRESS.md`'s current-sprint table.

**Note carried over, not touched by this CR:** the outreach template (Sprint 2) says only "14 dni
bezpłatnie" with no card mention either way — the 86 queued outreach messages stay valid as-is, no
re-assembly needed (per the Stakeholder's own note on this change).
