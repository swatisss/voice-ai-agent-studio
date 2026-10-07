---
type: API Contract
title: Mock healthcare and insurance business API
description: Synthetic member, claims, provider, policy, coverage, document, Green Card, renewal, onboarding, outreach and internal-reference endpoints the demo agents call as tools.
status: stable
tags: [api, mock, healthcare, insurance]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

Served by the platform at `/mock/*` (no `/api` prefix, no tenant header needed). Member-specific endpoints read the verified member from header `X-Member-Ref` (set by the tool executor after `verify_member`, [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)); without it they return **401** `{"error":"member_not_verified"}`. Data and rules: [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md). Responses are deterministic. Errors are `{"error": code, "detail": text}`.

# Member services (`/mock/healthcare`)

| Method | Path | Input | Output |
|---|---|---|---|
| POST | `/verify` | `{member_id, date_of_birth}` | `{verified: true, member_ref, first_name, plan_name}` or `{verified: false, reason}` |
| GET | `/benefits` | member | `{plan_name, plan_type, deductible: {individual, met, remaining}, out_of_pocket_max: {…}, copays: {…}, referral_required_for_specialists}` |
| GET | `/claims` | member | `{claims: [{claim_id, type, service, service_date, status}]}` newest first |
| GET | `/claims/{claim_id}` | member | `{claim_id, type, service, provider, service_date, status, billed, plan_paid, member_responsibility, paid_date, denial_reason, appeal_deadline, expected_decision_date, notes, timeline: [{date, event}], next_step}`; 404 if not the member's |
| GET | `/prior-auths/{auth_id}` | member | `{auth_id, service, status, decision_date, valid_through, expected_decision_date, notes}`; 404 if not the member's (catalog endpoint, not a tool) |
| GET | `/providers` | `specialty`, `zip?` | `{providers: [{name, specialty, practice, address, zip, phone, accepting_new_patients, network}]}`; exact zip first |

# Insurance (`/mock/insurance`)

| Method | Path | Input | Output |
|---|---|---|---|
| GET | `/policies` | member | `{policies: [{policy_id, type, product, status, start_date, renewal_date}]}` |
| GET | `/policies/{policy_id}` | member | `{policy_id, type, product, status, start_date, end_date, renewal_date, annual_premium, payment_frequency, payment_status, next_payment_date, overdue_amount, grace_period_ends, cover_level, insured_persons, deductible?, vehicle?, voluntary_excess?, renewal_status}`; 404 if not the member's |
| GET | `/policies/{policy_id}/coverage` | member; `benefit` | `{policy_id, benefit, covered, annual_limit, used, remaining, waiting_period_days, pre_authorization_required, copay_percent, notes}`; unknown benefit 422; motor policy 409 `not_applicable`; `covered: false` benefits return no limit |
| GET | `/documents` | member; `policy_id` | `{policy_id, documents: [{document_type, title, delivery_options}]}` for that policy type |
| POST | `/documents/request` | member; `{policy_id, document_type, delivery: email\|download\|post, countries?, travel_start?, travel_end?}` | `{request_id, document_type, delivery, status, eta, sent_to?, download_url?, valid_from?, valid_to?, countries?}`; errors below |
| GET | `/policies/{policy_id}/renewal-quote` | member | `{policy_id, product, renewal_date, days_to_renewal, current_premium, renewal_premium, change_percent, reasons, options: [{name, premium, notes}], renewal_status}`; outside 90 days 409 `not_in_renewal_window` |
| POST | `/policies/{policy_id}/renewal-decision` | member; `{decision: accept\|decline\|callback, option?, callback_time?, note?}` | `{reference, policy_id, renewal_status}`; `callback` requires `callback_time` (422) |
| GET | `/onboarding` | member | `{policy_id, status: in_progress\|complete, steps: [{step_id, title, status: done\|pending}], remaining}` |
| POST | `/onboarding/steps/{step_id}` | member; `{value?}` | updated checklist; unknown step 404; `communication_preferences` needs `value` in `email`, `sms`, `post` (422) |
| GET | `/outreach/renewals` | — | `{targets: [{member_ref, first_name, summary, context}]}`: policies renewing within 60 days with a pending renewal, nearest first; `context` has `member_id`, `policy_id`, `product`, `renewal_date`, `days_to_renewal`, `premium_change_percent`, `purpose` |
| GET | `/outreach/onboarding` | — | same shape for members with open onboarding steps; `context` has `member_id`, `policy_id`, `product`, `steps_remaining`, `purpose` |

**Document request errors**: unknown policy or not the member's → 404; `document_type` not offered for that policy type → 409 `document_not_available`; `delivery` not offered → 409 `delivery_not_available`. **Green Card** (`document_type: green_card`): policy not motor → 409 `not_a_motor_policy`; policy not active → 409 `policy_not_active`; missing `countries`, `travel_start` or `travel_end` → 422; a country outside the covered list → 409 `country_not_covered` with `unsupported_countries` and `covered_countries`; travel longer than 90 days or starting outside today…today+60 → 422 `invalid_travel_dates`; delivery `post` → 409 `delivery_not_available`. Success returns `valid_from`/`valid_to` (the travel dates), `countries` and a download URL or masked email.

# Internal (`/mock/internal`)

| Method | Path | Input | Output |
|---|---|---|---|
| GET | `/authorization-limits` | `role?`, `claim_type?` | with both: `{role, claim_type, limit, cosign_required_above}`; with `role` only: its limits; without: all roles. Unknown role 404 |
| GET | `/contacts` | `topic` | `{topic, team, contact, extension, hours, email}`; unknown topic 404 with the list of topics |

# Normalization rules

* `member_id`: strip everything except letters/digits, uppercase; accept with or without the `EVG` prefix (`482913`, `EVG-482913`, `evg 482913` all match `EVG-482913`).
* `date_of_birth`: accept `YYYY-MM-DD`, `MM/DD/YYYY`, `M/D/YYYY`, and month-name forms like `April 12 1986` / `12 April 1986`.
* `claim_id` / `auth_id` / `policy_id` / `step_id`: case-insensitive, optional dash (`c20931` → `C-20931`, `hp100231` → `HP-100231`).
* `specialty`, `benefit`, `topic`, `country`: case-insensitive; `benefit` also accepts spaces (`mental health` → `mental_health`).

# Acceptance

- **MOCK-01** — Given `{member_id: "482913", date_of_birth: "April 12, 1986"}`, when verifying, then the result is `verified: true` with `member_ref: "EVG-482913"`.
- **MOCK-02** — Given `X-Member-Ref: EVG-482913`, when requesting claim `C-31544` (James Carter's), then the response is 404.
- **MOCK-03** — Given no `X-Member-Ref`, when requesting `/benefits`, then the response is 401 `{error: "member_not_verified"}`.
- **MOCK-04** — Given `specialty=derm&zip=94110`, then Mission Dermatology is returned first.
- **MOCK-05** — Given a verified member, when listing policies and opening a policy of another member, then the list contains only the member's policies, the details include premium, payment status and renewal date, and the other member's policy returns 404; without verification both return 401.
- **MOCK-06** — Given Maria's health policy, when asking for `dental` coverage, then `remaining` equals the annual limit minus used, with the waiting period and co-pay; a benefit the plan does not cover returns `covered: false`; asking for coverage on a motor policy returns 409 `not_applicable`.
- **MOCK-07** — Given a health policy and a motor policy, when listing documents, then `green_card` appears only for the motor policy; requesting a document by email returns a masked address and a 15-minute ETA, by post a 5–7 business day ETA, by download a link.
- **MOCK-08** — Given James's active motor policy, when a Green Card is requested for Spain with valid dates, then it is issued with `valid_from`/`valid_to`; for the USA it returns 409 `country_not_covered`; for 120 days it returns 422; for a health policy 409 `not_a_motor_policy`; by post 409 `delivery_not_available`.
- **MOCK-09** — Given policies in and out of the renewal window, when requesting a quote, then in-window policies return premium, change percent, reasons and options, others return 409; recording `accept` sets `renewal_status` to `accepted` (visible on the next quote), `callback` without a time returns 422.
- **MOCK-10** — Given Aisha's onboarding checklist, when `confirm_contact_details` is already done and `communication_preferences` is completed with `email`, then `remaining` drops by one; an invalid preference returns 422 and an unknown step 404.
- **MOCK-11** — Given the outreach endpoints, then renewals list James, Maria and Robert in that order and drop a policy once its renewal is decided; onboarding lists only members with open steps.
- **MOCK-12** — Given the internal endpoints, then they work without a member header; `claims_handler` inpatient limit is 5,000; an unknown topic returns 404 listing the valid topics.
