# BACKLOG.md — Parked Ideas

> Anything that is not in the current sprint goes here. Reviewed ONLY at sprint boundaries.
> Nothing here is a commitment. PM proposes, Stakeholder decides at gates.

## Parked (from planning conversations)

| Idea | Origin | Earliest slot |
|---|---|---|
| **Sprint 4 hardening batch (COMMITTED, not optional):** RDS → private subnets + VPC connector + NAT; remove 0.0.0.0/0 rule; move secrets to Secrets Manager + App Runner instance role | Ticket 0.5 networking decision (2026-08-05) | **Sprint 4 start — hard gate before first customer data** |
| ~~Admin: customers view~~ → **PULLED INTO SPRINT 5 as ticket 5.6** (Stakeholder, 2026-08-07) | Stakeholder question during Sprint 5 | Sprint 5 ✅ scheduled |
| **Pipeline ops in admin panel** (scoped per Stakeholder 2026-08-05): "Run pipeline now" button (district picker, live progress), polling schedule on/off + frequency config, cost-cap editing, per-run spend history. Requires real auth (Sprint 4) before any money-spending buttons exist in UI | Sprint 1 planning idea, expanded in Sprint 2 planning chat | Sprint 6 or right after |
| Outreach follow-up sequences (2nd touch) | LOGIC.md v1 outreach constraints | After G2 |
| Auto-post responses via Google Business Profile API ("Approve & post" in email) | Product plan | After G4 (10 paying customers) |
| WhatsApp delivery of alerts | Product plan | Post-launch |
| Hotels niche | Brief | After restaurant validation |
| Short-term rental apartments niche | Brief | After hotels |
| Second city expansion | Roadmap | After G4 |
| Response tone presets + "what we can offer" field feeding the prompt | PM suggestion | Sprint 6 or later |
| Landing page A/B on demo block | PM suggestion | Post-launch |
| Multi-location support for restaurant groups | PM suggestion | Post-launch |
| English/international version | — | Far future |
| Serious-allegation flag: extend §2-style gating beyond health to crime/theft/harassment/discrimination keyword classes — leads with such reviews never auto-queue | Lead 76 (Mezza Lounge & Bar), 2026-08-09 | Sprint 6 |
| `/health` returns the git commit sha — deploy evidence today is "the push and the deploy timestamps line up", not a direct read from the running process | Ticket 5.8 deploy verification, 2026-08-09 | Sprint 6 |
| Customer alerts pagination — Historia goes stale past `ALERTS_LIST_LIMIT=30`; add paging/load-more before any real customer approaches 30 stored alerts | Ticket 6.9 volume flag, 2026-08-16 | Before any customer nears the 30-alert cap |
| Connect-flow provenance — persist the search query typed (or maps_url pasted) and which result the customer chose at `POST /api/customer/connect-place`/`GET /api/customer/search-place` time, so a future "wrong restaurant" dispute is verifiable from a log instead of inferred from near-name absence in `places` | Ticket 6.15's Q1b audit-trail gap (option 3), 2026-08-18 | Sprint 6 or later |

## How to add

One line, link the origin (chat date or ticket), no design docs here. If it takes more than a line,
it is trying to become scope — resist.
