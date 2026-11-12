---
type: API Contract
title: Mock Northgate Health business API
description: Synthetic member services, payments, documents, Digital GP, cash plan, cover check, specialist finder, pre-authorisation, claims, quote, underwriting, application and outreach endpoints the demo agents call as tools.
status: stable
tags: [api, mock, healthcare, insurance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

Served by the platform at `/mock/*` (no `/api` prefix, no tenant header needed). Member-specific endpoints read the verified member from header `X-Member-Ref` (set by the tool executor after `verify_member`, [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)); without it they return **401** `{"error":"member_not_verified"}`. Sales endpoints need no member (callers are not members yet). Data and rules: [/demo-data/northgate-members.md](/demo-data/northgate-members.md). Responses are deterministic for a given day. Errors are `{"error": code, "detail": text}`. Money is in pounds.

# Member services (`/mock/healthcare`)

| Method | Path | Input | Output |
|---|---|---|---|
| POST | `/verify` | `{member_id, date_of_birth}`, or `{date_of_birth}` with header `X-Identified-Ref` (flow A) | `{verified: true, member_ref, first_name, plan_name}` or `{verified: false, reason}` |
| POST | `/identify` | `{phone}` (E.164 or UK national `07…`) | `{matched: true, member_ref, first_name}` or `{matched: false}`; never more ([/architecture/caller-verification.md](/architecture/caller-verification.md)) |
| GET | `/members/me` | member | `{first_name, plan_name, policies: [{policy_id, product, status}], open_claims: [{claim_id, status}], preferred_contact}` ([/architecture/agent-memory.md](/architecture/agent-memory.md)) |
| GET | `/members/me/contact` | member | `{email, mobile}`: the contact on the member's record, `mobile` the registered phone number in E.164 or `null`; read by the contact tools only at the moment of sending and never stored ([/architecture/contact-tools.md](/architecture/contact-tools.md), CP-0040) |
| GET | `/gp/slots` | member; `type: gp\|nurse`, `format?: video\|phone` | `{clinician, hours, slots: [{slot_id, date, time, format}]}` up to 4 free slots; cash-plan-only member 409 `not_covered` |
| POST | `/gp/appointments` | member; `{slot_id, reason, patient_name?}` | `{booking_id, date, time, clinician, format, patient, reason, how_to_join}`; unknown slot 404; taken 409 `slot_taken`; patient not on the health policy 409 `patient_not_covered` |
| GET | `/claims` | member | `{claims: [{claim_id, service, service_date, status}]}` newest first |
| GET | `/claims/{claim_id}` | member | `{claim_id, policy_id, service, provider, service_date, status, billed, plan_paid, member_responsibility, paid_date, denial_reason, expected_decision_date, notes, timeline, next_step}`; 404 if not the member's |
| GET | `/prior-auths/{auth_id}` | member | `{auth_id, policy_id, service, condition, status, decision_date, valid_through, expected_decision_date, consultant, hospital, notes}`; 404 if not the member's |
| GET | `/specialists` | `specialty?` or `condition?`, `postcode?`, `policy_id?` (with a member, filters to the member's hospital list) | `{specialty, hospital_list, specialists: [{specialist_id, name, hospital, fee_assured, first_available, video_or_phone}], note}` up to 3: same postcode area first, then fee-assured, then soonest; neither specialty nor condition 422 |
| POST | `/pre-authorisations` | member; `{policy_id, condition, treatment, symptoms_started, referral?, specialist_id?, gp_first_seen?, patient_name?}` | `{pre_auth_code, status: approved\|pending, policy_id, condition, treatment, specialist, hospital, valid_through, excess_to_pay, forms_needed, next_step, shortfall_warning?, note?}`; errors below |

# Insurance (`/mock/insurance`)

| Method | Path | Input | Output |
|---|---|---|---|
| GET | `/policies` | member | `{policies: [{policy_id, type: health\|cash_plan, product, status, start_date, renewal_date}]}` health first |
| GET | `/policies/{policy_id}` | member | `{policy_id, type, product, status, start_date, renewal_date, monthly_premium, payment_status, next_collection_date, insured_persons, cover, cooling_off_ends, exclusions}`; `cover` is excess, outpatient limit, hospital list, underwriting and add-ons (health) or level and yearly limits (cash plan); 404 if not the member's |
| GET | `/policies/{policy_id}/payments` | member | `{policy_id, payment_method, status, monthly_amount, collection_day, next_collection_date, bank_account, recent_payments, missed_amount, reinstate_by, what_happens?, retry?}` |
| POST | `/policies/{policy_id}/payments/retry` | member; `{collect_on?}` | `{reference, policy_id, amount, collect_on, bank_account, next_step}`; nothing missed 409 `nothing_missed`; date outside today+3…`reinstate_by` 422 |
| POST | `/policies/{policy_id}/payments/collection-day` | member; `{day}` | `{policy_id, collection_day, next_collection_date, amount, note}`; day outside 1–28 422; payment missed 409 `payment_missed` |
| POST | `/members/me/contact` | member; `{email?, mobile?, address?}` | `{reference, changed, confirmation_sent_to, note}`; nothing given 422; invalid email, non-UK mobile or address without a postcode 422 |
| POST | `/secure-links` | member; `{purpose: change_bank_details\|direct_debit_setup\|make_payment, channel: sms\|email, policy_id?}` | `{link_id, purpose, channel, sent_to (masked), expires_in_hours: 24}` |
| GET | `/documents` | member; `policy_id` | `{policy_id, documents: [{document_type, title, delivery_options}]}` for that policy type |
| POST | `/documents/request` | member; `{policy_id, document_type, delivery: email\|sms\|post}` | `{request_id, document_type, title, delivery, eta, status: queued\|scheduled, sent_to (masked)}`; not offered for the policy type 409 `document_not_available` with `available`; other delivery 409 |
| GET | `/policies/{policy_id}/eligibility` | member; `condition`, `treatment?` | `{policy_id, condition, treatment, covered, reason, referral_needed, direct_access_category, specialty, excess, excess_remaining, outpatient_limit, outpatient_remaining, hospital_list, forms_needed, next_step, note?}`; cash plan 409 `not_applicable` |
| GET | `/policies/{policy_id}/cash-benefits` | member | `{policy_id, level, refund_percent, benefits: [{benefit, yearly_limit, used, remaining}], how_to_claim}`; health policy 409 `not_a_cash_plan` |
| GET | `/cash-plan/claims` | member | `{claims: [{claim_id, benefit, provider, treatment_date, status}]}` |
| GET | `/cash-plan/claims/{claim_id}` | member | `{claim_id, policy_id, benefit, provider, treatment_date, amount_claimed, status, amount_paid, paid_date, expected_decision_date, notes}`; 404 if not the member's |
| GET | `/outreach/renewals` | — | `{targets: [{member_ref, first_name, summary, context}]}`: health policies renewing within 60 days, nearest first; `context` has `member_id`, `policy_id`, `product`, `renewal_date`, `days_to_renewal`, `purpose` (targets for outbound agents built in the Studio) |

**Cover check** (`/eligibility`, in this order): a missed payment → `covered: false` (cover suspended); the condition matches a personal exclusion → `covered: false`; the condition matches a moratorium condition → `covered: false`; Northgate Essentials with a diagnostic-only treatment (consultation, scan, test) → `covered: false`. `referral_needed` is false only for Direct Access conditions (muscles, bones and joints; mental health; cancer symptoms; moles and skin lesions). Moratorium policies list a pre-treatment form in `forms_needed`. A limited outpatient benefit reports `outpatient_remaining`.

**Pre-authorisation errors**: unknown or another member's policy 404; cash plan 409 `not_applicable`; condition or treatment shorter than 3 characters 422; no `symptoms_started` 422; not covered 409 `not_covered` with the reason; a referral needed and `referral` is not `open_referral`/`named_referral` 409 `referral_needed`; unknown `specialist_id` 404; specialist's hospital not on the member's list 409 `specialist_not_on_list`. Surgery words (surgery, operation, replacement, arthroscopy, removal, procedure, injection) make the code `pending` (waiting for the procedure code) instead of `approved`; approved codes are valid for 90 days. A specialist who is not fee-assured adds `shortfall_warning`. Codes continue from `PA-502001` and live until restart or `seed --reset`.

# Sales (`/mock/sales`)

| Method | Path | Input | Output |
|---|---|---|---|
| POST | `/quotes` | `{people: [{name?, date_of_birth, smoker?, relationship?: policyholder\|partner\|child}], postcode, start_date?, occupation?}` | `{quote_id, valid_until (+14 days), start_date, region, people: [{name, age, smoker}], packages: [{package, label, product, outpatient_limit, excess, hospital_list, add_ons, monthly_total, annual_total}], note}` |
| POST | `/quotes/{quote_id}/price` | `{package?, product?, outpatient_limit?, excess?, hospital_list?, add_ons?}` | `{quote_id, selection, monthly_total, annual_total, multi_person_discount_percent, add_ons_monthly, per_person, valid_until}`; stores the selection |
| POST | `/quotes/{quote_id}/underwriting` | `{method: moratorium\|full_medical\|switch, answers?: [{person, conditions, hazardous_activities}], previous_insurer?, continuous_cover_months?}` | `{underwriting_id, quote_id, method, method_explained, decision: accept\|accept_with_exclusions\|refer_to_underwriter, people: [{name, risk_score, risk_band, exclusions}], monthly_total, annual_total, next_step, refer_reasons?}` |
| POST | `/applications` | `{quote_id, underwriting_id, policyholder: {first_name, last_name, email, mobile, address}, documents_by?: email\|sms, payment_link_by?: email\|sms, key_facts_confirmed, declaration_confirmed, marketing_opt_in?}` | `{application_id, policy_id, membership_number, status: active_pending_direct_debit, cover, underwriting, exclusions, monthly_premium, start_date, first_collection_date, cooling_off_ends, documents_sent_to, direct_debit_link_sent_to, next_step}` |

**Quote rules**: 1 to 6 people (more 422); start date today…today+90 (422); a full UK postcode (422); the policyholder 18–79 and children up to 25 (422 `age_not_eligible`). Price per person = age-band base × product × outpatient limit × excess × hospital list × region × 1.10 if a smoker; the sum gets 5% off for two people and 10% for three or more, then add-ons are added per person (tables in [/demo-data/northgate-members.md](/demo-data/northgate-members.md)). Unknown or expired quote 404 / 409 `quote_expired`. Invalid option (for example an outpatient limit on Essentials) 422 `invalid_option`.

**Underwriting rules**: needs a priced selection (409 `no_cover_selected`). `full_medical` needs answers for everyone (422 `answers_required` with `missing`); each declared condition adds 12 points and an exclusion "<condition> and related conditions"; cancer, heart, stroke, kidney failure, multiple sclerosis or HIV, or a score of 80 or more, refers the case to an underwriter; full medical takes 5% off the core premium (add-ons are unchanged). `switch` needs a previous insurer and at least 12 months of continuous cover (409 `switch_not_eligible`). Score = 10 + 3 per decade of age + 15 smoker + 10 hazardous activities (+ 12 per condition); band low < 40 ≤ medium < 60 ≤ high.

**Application rules**: underwriting not for this quote 404; referred 409 `referred_to_underwriter`; `key_facts_confirmed` or `declaration_confirmed` false 422 `confirmation_required`; invalid email or non-UK mobile 422; one policy per quote (409 `already_applied`). Success creates a member (`NGH-96xxxx`, verifiable with the policyholder's date of birth), a policy (`PMI-31xxxx`) with cooling-off to start + 21 days, first collection at start + 10 days, and personal exclusions from full medical underwriting.

# Normalization rules

* `member_id`: letters and digits only, uppercase; the `NGH` prefix is optional (`410237`, `NGH-410237`, `ngh 410237` all match `NGH-410237`).
* Dates: `YYYY-MM-DD`, UK numeric `DD/MM/YYYY`, and spoken forms `14 March 1984`, `14th of March 1984`, `March 14 1984`.
* `claim_id` / `auth_id` / `policy_id` / quote and underwriting references: case-insensitive, optional dash (`cl70231` → `CL-70231`).
* `phone`: digits only; UK national `07…` becomes `+447…`.
* `specialty`, `benefit`, `purpose`, `method`, options: case-insensitive; spaces and dashes become underscores.

# Acceptance

- **MOCK-01** — Given `{member_id: "410237", date_of_birth: "14 March 1984"}`, when verifying, then the result is `verified: true` with `member_ref: "NGH-410237"`; a wrong date gives `verified: false`.
- **MOCK-02** — Given `X-Member-Ref: NGH-410237`, when requesting claim `CL-70640` (Raj Patel's), then the response is 404.
- **MOCK-03** — Given no `X-Member-Ref`, when requesting `/mock/insurance/policies`, then the response is 401 `{error: "member_not_verified"}`.
- **~~MOCK-04~~** — Retired by CP-0039: the US provider directory is replaced by the specialist finder (MOCK-25). Was: `specialty=derm&zip=94110` returned Mission Dermatology first.
- **MOCK-05** — Given a verified member, when listing policies and opening a policy of another member, then the list contains only the member's policies, the details include the monthly premium, cover and payment status, and the other member's policy returns 404.
- **~~MOCK-06~~** — Retired by CP-0039: benefit limits with US co-pays are replaced by the cover check (MOCK-24) and cash plan benefits (MOCK-23).
- **~~MOCK-07~~** — Retired by CP-0039: Green Card documents no longer exist; documents are MOCK-21.
- **~~MOCK-08~~** — Retired by CP-0039: Green Card issuing removed with the motor policies.
- **~~MOCK-09~~** — Retired by CP-0039: renewal quotes removed with the Renewal Outreach Agent.
- **~~MOCK-10~~** — Retired by CP-0039: onboarding checklist removed with the Welcome & Onboarding Agent.
- **~~MOCK-11~~** — Retired by CP-0039: the renewal and onboarding outreach lists are replaced by MOCK-30.
- **~~MOCK-12~~** — Retired by CP-0039: internal reference endpoints removed with the Internal Knowledge Assistant.
- **~~MOCK-13~~** — Retired by CP-0039: claim first notice removed; Northgate claims start with a pre-authorisation (MOCK-26).
- **~~MOCK-14~~** — Retired by CP-0039: US claim requirements removed; how to claim is knowledge.
- **MOCK-15** — Given `{phone: "+447700900141"}` or `{phone: "07700 900141"}`, when identifying, then the result is `{matched: true, member_ref: "NGH-410237", first_name: "Sarah"}`; an unregistered number gives `{matched: false}` only.
- **MOCK-16** — Given header `X-Identified-Ref: NGH-410237` and `{date_of_birth: "1984-03-14"}`, when verifying, then the result is `verified: true`; with another date it is `verified: false`; with neither a member ID nor the header it is 422 `member_id_required`.
- **MOCK-17** — Given `X-Member-Ref: NGH-410237`, when requesting `/members/me`, then the profile lists Sarah Mitchell's plan, her policy and her open claims and nothing about other members.
- **MOCK-18** — Given David Okoro's policy `PMI-300214` with a missed £61.20 payment, when reading payments and then retrying with no date, then payments show `status: missed`, `missed_amount: 61.2` and a `reinstate_by` date, and the retry is scheduled 3 days ahead with a `RT-` reference; a second retry returns 409 `nothing_missed`, and a retry date after `reinstate_by` returns 422.
- **MOCK-19** — Given Emma Clarke's policy, when the collection day is set to 15, then the next collection date is the 15th of next month; day 31 returns 422, and David's policy with a missed payment returns 409 `payment_missed`.
- **MOCK-20** — Given a verified member, when updating the email address, then the change returns a `CH-` reference and a masked confirmation address; an address without a postcode returns 422; and a secure link for `change_bank_details` by sms returns a `SL-` link sent to the masked mobile, expiring in 24 hours, with no bank details anywhere in the request or response.
- **MOCK-21** — Given a health policy and a cash plan, when listing documents, then `membership_certificate` is offered only for the health policy and `table_of_benefits` only for the cash plan; requesting the membership certificate by email returns `status: queued` with a masked email; post returns `scheduled`; `table_of_benefits` on a health policy returns 409 `document_not_available`.
- **MOCK-22** — Given Sarah Mitchell, when listing GP video slots and booking one for "Isla", then the booking returns a `GPB-` reference for Isla Mitchell and the slot disappears from the list; booking it again returns 409 `slot_taken`; a patient not on the policy returns 409 `patient_not_covered`; Lucy Evans (cash plan only) gets 409 `not_covered` for slots.
- **MOCK-23** — Given Lucy Evans's Level 3 cash plan, when reading benefits, then optical shows limit 200 and dental shows used 145 and remaining 255; claim `CC-81377` is `processing` with an expected decision date; a health policy returns 409 `not_a_cash_plan`.
- **MOCK-24** — Given the cover check, then Sarah's knee pain with an MRI scan is covered with no referral needed (Direct Access) and a pre-treatment form (moratorium); Raj's back pain is not covered (exclusion); Emma's migraine is not covered (moratorium); David's anything is not covered (payment missed); Tom's consultation is not covered (Essentials, diagnostics); Tom's knee osteoarthritis with a knee replacement is covered and needs a referral; Emma's consultation reports `outpatient_remaining: 360`.
- **MOCK-25** — Given `condition=knee pain&postcode=LS6 2AB&policy_id=PMI-300101` for Sarah, when finding specialists, then up to three orthopaedic specialists on the Extended list are returned with Leeds ones first and fee-assured before not fee-assured; a London Premium-only specialist never appears for her; no specialty and no condition returns 422.
- **MOCK-26** — Given Sarah verified, when a pre-authorisation for knee pain, a consultation with `CN-101` and Direct Access is created, then it is `approved` with a `PA-502001` code valid for 90 days and `excess_to_pay: 0`; a knee arthroscopy is `pending`; Raj's back pain returns 409 `not_covered`; Tom's knee osteoarthritis and knee replacement with `referral: none` returns 409 `referral_needed`; a missing `symptoms_started` returns 422; `CN-106` (London Premium only) returns 409 `specialist_not_on_list`; Emma's shoulder pain consultation with the not fee-assured `CN-103` has a `shortfall_warning`.
- **MOCK-27** — Given two adults born 1990-05-05 and 1992-02-02 in BS6 6JY, when quoting, then three packages are returned cheapest first (Essentials, Balanced, Complete), the quote is valid for 14 days, and pricing Balanced with the dental and optical add-on gives a 5% two-person discount and `add_ons_monthly: 23.0`; a smoker costs 10% more than the same non-smoker; a London postcode costs more than a Bristol one; an outpatient limit on Essentials returns 422; a policyholder aged 80 returns 422 `age_not_eligible`.
- **MOCK-28** — Given a priced quote, when underwriting with full medical answers naming asthma for one person, then the decision is `accept_with_exclusions` with "asthma and related conditions" and the price is 5% lower than moratorium; a heart condition gives `refer_to_underwriter`; answers for only one of two people give 422 `answers_required`; `switch` with 6 months of cover gives 409 `switch_not_eligible`; underwriting before pricing gives 409 `no_cover_selected`.
- **MOCK-29** — Given an accepted underwriting result, when creating the application without `key_facts_confirmed` it returns 422 `confirmation_required`; with both confirmations it returns a `PMI-31` policy, an `NGH-96` membership number, cooling-off at start + 21 days, masked document and Direct Debit link destinations, and the new member can then verify with the policyholder's date of birth and see the policy; a second application for the same quote returns 409 `already_applied`; a referred case returns 409 `referred_to_underwriter`.
- **MOCK-30** — Given the seeded policies, when listing renewal outreach, then Sarah Mitchell's policy renewing in 45 days is the only target, with `member_id`, `policy_id`, `days_to_renewal` and `purpose` in its context.
- **MOCK-31** — Given dates spoken the UK way ("14th of March 1984", "14/03/1984", "14 Mar 1984"), when verifying, then each parses to 1984-03-14; a `DD/MM/YYYY` date is never read as `MM/DD/YYYY`.
- **MOCK-32** — Given `X-Member-Ref: NGH-410237`, when requesting `/members/me/contact`, then the result is `{email: "sarah.mitchell@example.co.uk", mobile: "+447700900141"}`; for NGH-714560 (Raj Patel, no registered number) `mobile` is `null`; without the header it is 401.
