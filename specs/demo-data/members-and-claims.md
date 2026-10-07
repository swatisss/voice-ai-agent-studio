---
type: Seed Data
title: Members, policies, claims and business records
description: Synthetic records behind the mock insurance API - members, plans and benefits, policies, claims, prior authorizations, providers, documents, renewal quotes, onboarding checklists, outreach lists and internal reference data.
status: stable
tags: [demo-data, seed, mock]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

Everything is synthetic. Dates written `T±n` are relative to the day the app runs (`T` = today), so renewal windows stay valid whenever the demo is given. Claim dates are fixed.

# Plans

| Plan | Type | Deductible | OOP max | PCP | Specialist | Urgent care | ER | Telehealth | Referral for specialists |
|---|---|---|---|---|---|---|---|---|---|
| Evergreen Silver PPO | PPO | $1,500 | $6,000 | $30 | $35 | $60 | $250 | $0 | no |
| Evergreen Gold HMO | HMO | $500 | $4,000 | $20 | $40 | $50 | $200 | $0 | yes |
| Evergreen Bronze EPO | EPO | $4,000 | $8,500 | $45 | $75 | $90 | $400 | $15 | no |

# Members

| member_ref | name | DOB | email | plan | deductible met | OOP met |
|---|---|---|---|---|---|---|
| EVG-482913 | Maria Lopez | 1986-04-12 | maria.lopez@example.com | Silver PPO | $850 | $1,200 |
| EVG-337120 | James Carter | 1979-11-02 | james.carter@example.com | Gold HMO | $500 | $1,450 |
| EVG-559804 | Priya Nair | 1992-07-23 | priya.nair@example.com | Silver PPO | $300 | $410 |
| EVG-610277 | Robert Chen | 1958-01-30 | robert.chen@example.com | Gold HMO | $500 | $2,980 |
| EVG-725031 | Aisha Okafor | 1990-09-15 | aisha.okafor@example.com | Bronze EPO | $1,120 | $1,120 |
| EVG-801456 | Daniel Kim | 2001-03-08 | daniel.kim@example.com | Silver PPO | $0 | $60 |

# Policies

| policy_id | member | type | product | status | start | end / renewal | annual premium | payments | payment status | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| HP-100231 | Maria | health | Evergreen Silver PPO | active | T−340 | T+25 | $2,548.80 | monthly | up to date, next payment T+9 | |
| HP-100412 | James | health | Evergreen Gold HMO | active | T−280 | T+85 | $3,120.00 | monthly | up to date | |
| MP-200415 | James | motor | Evergreen Motor Comprehensive | active | T−352 | T+13 | $684.00 | annual | up to date | vehicle: Toyota Corolla 2020, reg DEMO-4821 |
| HP-100655 | Priya | health | Evergreen Silver PPO | active | T−200 | T+165 | $2,548.80 | monthly | up to date | |
| HP-100790 | Robert | health | Evergreen Gold HMO | active | T−300 | T+55 | $3,120.00 | monthly | **overdue** $212.40, grace period ends T+7 | |
| HP-100877 | Aisha | health | Evergreen Bronze EPO | active | T−7 | T+358 | $1,980.00 | monthly | up to date | new policyholder |
| HP-100901 | Daniel | health | Evergreen Silver PPO | active | T−21 | T+344 | $2,548.80 | monthly | up to date | new policyholder |

Insured persons: the member only. Policy details also return the cover level (plan name), the plan deductible and, for motor, the vehicle and voluntary excess ($250).

# Benefits by plan (annual limits per person)

| Benefit | Silver PPO | Gold HMO | Bronze EPO |
|---|---|---|---|
| inpatient | covered, no limit, pre-auth, wait 0 d | covered, no limit, pre-auth, wait 0 d | covered, no limit, pre-auth, wait 0 d |
| outpatient | $5,000, 10% co-pay, wait 0 d | $8,000, 0% co-pay, wait 0 d | $2,000, 20% co-pay, wait 0 d |
| maternity | $10,000, wait 365 d, pre-auth | $15,000, wait 365 d, pre-auth | $5,000, wait 365 d, pre-auth |
| dental | $800, 20% co-pay, wait 90 d | $1,500, 10% co-pay, wait 60 d | **not covered** |
| optical | $300, wait 30 d | $500, wait 30 d | **not covered** |
| mental_health | $4,000, wait 0 d | $6,000, wait 0 d | $2,000, wait 0 d |
| physiotherapy | $1,200, referral, wait 0 d | $2,000, referral, wait 0 d | $600, referral, wait 0 d |

Amounts used this year (default $0): Maria: outpatient $1,850, dental $320, mental_health $600. Priya: dental $100, outpatient $410. Daniel: outpatient $60.

# Claims

| claim_id | member | type | service | provider | date | billed | status | plan paid | member owes | notes and timeline |
|---|---|---|---|---|---|---|---|---|---|---|
| C-20931 | Maria | health | Office visit – dermatology | Mission Dermatology | 2026-09-10 | $220 | paid (2026-09-28) | $185 | $35 | specialist copay. Timeline: 09-10 received → 09-18 reviewed → 09-28 paid |
| C-20977 | Maria | health | Lab work – lipid panel | Quest Diagnostics | 2026-09-18 | $140 | processing | — | — | decision expected T+4. Timeline: 09-18 received → 09-25 in review |
| C-31544 | James | health | Emergency appendectomy | Lakeside Surgical Center | 2026-08-29 | $18,400 | denied | $0 | — | denial: out-of-network facility; appeal deadline 2027-02-25 |
| C-31602 | James | health | Emergency room visit | Bayview Medical Center | 2026-08-29 | $2,150 | paid (2026-09-15) | $1,950 | $200 | ER copay |
| C-40210 | Priya | health | MRI lumbar spine | Bay Imaging | 2026-09-22 | $1,850 | pending information | — | — | provider asked to send authorization number PA-77812 |
| C-41007 | Robert | health | Physical therapy, 6 visits | Harbor Physical Therapy | 2026-09-05 | $900 | paid (2026-09-25) | $660 | $240 | 6 × $40 specialist copay |
| C-52230 | Aisha | health | Urgent care visit | CityCare Urgent Care | 2026-09-30 | $310 | paid (2026-10-03) | $220 | $90 | urgent care copay |
| C-60012 | James | motor | Windscreen replacement | Clearview Glass | 2026-09-02 | $410 | paid (2026-09-12) | $410 | $0 | glass cover, no excess. Timeline: 09-02 received → 09-05 approved → 09-12 paid |

Every claim also returns a `timeline` (date, event) list and a `next_step` sentence (for example "No action needed", "Expect a decision by <date>", "An appeals specialist can file an appeal").

# Prior authorizations (catalog endpoint only; not a tool in v1)

| auth_id | member | service | status | details |
|---|---|---|---|---|
| PA-77812 | Priya | MRI lumbar spine | approved | approved 2026-09-20, valid through 2026-12-20 |
| PA-77930 | Aisha | Knee arthroscopy | pending clinical review | decision expected T+3 |
| PA-78001 | Robert | CPAP device | denied | insufficient documentation; the provider may resubmit with a sleep study |

# Providers (in-network)

| name | specialty | practice | zip | phone | new patients |
|---|---|---|---|---|---|
| Dr. Elena Ruiz | Dermatology | Mission Dermatology | 94110 | (415) 555-0110 | yes |
| Dr. Samuel Park | Dermatology | Sunset Skin Clinic | 94122 | (415) 555-0127 | no |
| Dr. Grace Liu | Primary care | Bayview Family Medicine | 94124 | (415) 555-0133 | yes |
| Dr. Marcus Bell | Orthopedics | Lakeside Orthopedics | 94115 | (415) 555-0148 | yes |
| Harbor Mental Health Associates | Behavioral health | Harbor Mental Health | 94103 | (415) 555-0156 | yes |
| Dr. Hannah Wright | Pediatrics | Little Steps Pediatrics | 94110 | (415) 555-0161 | yes |
| Dr. Naomi Reyes | Dentistry | Mission Family Dental | 94110 | (415) 555-0172 | yes |

# Documents

| document_type | title | health | motor | delivery |
|---|---|---|---|---|
| policy_schedule | Policy schedule | yes | yes | email, download, post |
| policy_wording | Policy wording | yes | yes | email, download, post |
| membership_card | Membership card | yes | — | email, download, post |
| certificate_of_insurance | Certificate of insurance | — | yes | email, download, post |
| premium_invoice | Premium invoice | yes | yes | email, download, post |
| tax_certificate | Annual premium statement | yes | — | email, download, post |
| green_card | Green Card (international motor insurance certificate) | — | yes | email, download |

Delivery: **email** to the address on file (returned masked, for example `m***@example.com`), ready in 15 minutes; **download** link on `https://portal.evergreen.example/…`, instant; **post** to the address on file, 5–7 business days.

**Green Card rules** (synthetic): motor policy, status active; at least one destination country, all in *Austria, Belgium, Denmark, France, Germany, Greece, Ireland, Italy, Netherlands, Norway, Portugal, Spain, Sweden, Switzerland, Turkey*; travel start between today and 60 days ahead; travel period at most 90 days; delivery email or download.

# Renewal quotes (policies renewing within 90 days)

| policy | current → renewal | change | reasons | options |
|---|---|---|---|---|
| MP-200415 (James) | $684.00 → $738.70 | +8.0% | repair cost inflation; one claim in the last 12 months | Renew as is $738.70; Increase voluntary excess to $500: $689.30 (saves $49.40) |
| HP-100231 (Maria) | $2,548.80 → $2,651.00 | +4.0% | medical cost inflation (3.2%); moving into the 35–39 age band | Renew as is $2,651.00; Pay annually $2,518.45 (5% discount) |
| HP-100790 (Robert) | $3,120.00 → $3,214.00 | +3.0% | medical cost inflation (3.2%) | Renew as is $3,214.00 |
| HP-100412 (James) | $3,120.00 → $3,214.00 | +3.0% | medical cost inflation | Renew as is $3,214.00 |

Other policies are outside the renewal window (409 `not_in_renewal_window`). Decisions (`accept`, `decline`, `callback`) set the policy's renewal status to `accepted`, `declined` or `callback_requested`.

# Onboarding checklists (new policyholders)

Steps: `confirm_contact_details`, `communication_preferences` (email · sms · post), `register_online_account`, `download_membership_card`, `choose_primary_provider`, `review_waiting_periods`.

* Aisha Okafor (HP-100877): `confirm_contact_details` done; five pending.
* Daniel Kim (HP-100901): `confirm_contact_details`, `register_online_account`, `download_membership_card` done; three pending.

# Outreach lists

* **Renewals**: policies renewing within 60 days whose renewal is still pending, nearest first: MP-200415 James (13 days), HP-100231 Maria (25), HP-100790 Robert (55).
* **Onboarding**: members with open steps: Aisha Okafor, Daniel Kim.

# Internal reference data

**Authorization limits** (USD, per claim): claims_handler: inpatient 5,000 · outpatient 2,000 · dental 1,000; senior_handler: 25,000 · 10,000 · 5,000; team_leader: 100,000 · 50,000 · 20,000; claims_manager: 250,000 · 100,000 · 50,000 (director co-signature above these).

**Escalation contacts** (fictional): fraud — Special Investigations Unit, ext. 4410; complaints — Customer Resolution Team, ext. 4120; legal — Legal & Compliance, ext. 4600; data_protection — Privacy Office, ext. 4700; it_service_desk — IT Service Desk, ext. 4000; medical_director — Clinical Governance, ext. 4850. Each has hours and an `@evergreen.example` email.

# Nurse line

24/7 nurse line: **1-800-555-0142** (fictional).
