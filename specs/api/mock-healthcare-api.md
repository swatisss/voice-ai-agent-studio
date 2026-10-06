---
type: API Contract
title: Mock healthcare business API
description: Synthetic member, benefits, claims, prior-authorization, provider, ID card and pharmacy endpoints the demo agents call as tools.
status: stable
tags: [api, mock, healthcare]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

Served by the platform at `/mock/*` (no `/api` prefix, no tenant header required, but `X-Member-Ref` is honored). Data: [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md). Responses are deterministic.

# Member services (`/mock/healthcare`)

| Method | Path | Input | Output |
|---|---|---|---|
| POST | `/verify` | `{member_id, date_of_birth}` | `{verified: true, member_ref, first_name, plan_name}` or `{verified: false, reason}` |
| GET | `/benefits` | header `X-Member-Ref` | `{plan_name, plan_type, deductible: {individual, met, remaining}, out_of_pocket_max: {individual, met, remaining}, copays: {primary_care, specialist, urgent_care, emergency_room, telehealth}, referral_required_for_specialists}` |
| GET | `/claims` | header `X-Member-Ref` | `{claims: [{claim_id, service, service_date, status}]}` (newest first) |
| GET | `/claims/{claim_id}` | header `X-Member-Ref` | `{claim_id, service, provider, service_date, status, billed, plan_paid, member_responsibility, paid_date, denial_reason, appeal_deadline, expected_decision_date, notes}`; 404 if the claim does not belong to the member |
| GET | `/prior-auths/{auth_id}` | header `X-Member-Ref` | `{auth_id, service, status, decision_date, valid_through, expected_decision_date, notes}`; 404 if not the member's |
| GET | `/providers` | `specialty`, `zip?` | `{providers: [{name, specialty, practice, address, zip, phone, accepting_new_patients, network}]}` |
| POST | `/id-card` | header `X-Member-Ref`, `{reason?}` | `{request_id, mail_eta_business_days: "7-10", digital_card_available: true}` |

# Pharmacy (`/mock/pharmacy`)

| Method | Path | Input | Output |
|---|---|---|---|
| GET | `/formulary` | `drug` | `{drug, covered, tier, copay_30_day, prior_auth_required, quantity_limit, alternatives}` or 404 |
| GET | `/refills/{rx_id}` | header `X-Member-Ref` | `{rx_id, drug, refills_remaining, last_fill_date, next_eligible_date, pharmacy}` |

# Normalization rules

* `member_id`: strip everything except letters/digits, uppercase; accept with or without the `EVG` prefix (`482913`, `EVG-482913`, `evg 482913` all match `EVG-482913`).
* `date_of_birth`: accept `YYYY-MM-DD`, `MM/DD/YYYY`, `M/D/YYYY`, and month-name forms like `April 12 1986` / `12 April 1986`.
* `claim_id` / `auth_id` / `rx_id`: case-insensitive, optional dash (`c20931` → `C-20931`).
* `specialty`: case-insensitive substring match (`derm` matches Dermatology).

# Acceptance

- **MOCK-01** — Given `{member_id: "482913", date_of_birth: "April 12, 1986"}`, when verifying, then the result is `verified: true` with `member_ref: "EVG-482913"`.
- **MOCK-02** — Given `X-Member-Ref: EVG-482913`, when requesting claim `C-31544` (James Carter's), then the response is 404.
- **MOCK-03** — Given no `X-Member-Ref`, when requesting `/benefits`, then the response is 401 `{error: "member_not_verified"}`.
- **MOCK-04** — Given `specialty=derm&zip=94110`, then Mission Dermatology is returned first.
