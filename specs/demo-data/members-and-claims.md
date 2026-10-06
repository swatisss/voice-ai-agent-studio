---
type: Seed Data
title: Members, claims and business records
description: Synthetic records behind the mock healthcare API - members, plans, accumulators, claims, prior authorizations, providers and pharmacy data.
status: stable
tags: [demo-data, seed, mock]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Plans

| Plan | Type | Deductible | OOP max | PCP | Specialist | Urgent care | ER | Telehealth | Specialist referral |
|---|---|---|---|---|---|---|---|---|---|
| Evergreen Silver PPO | PPO | $1,500 | $6,000 | $30 | $35 | $60 | $250 | $0 | no |
| Evergreen Gold HMO | HMO | $500 | $4,000 | $20 | $40 | $50 | $200 | $0 | yes |
| Evergreen Bronze EPO | EPO | $4,000 | $8,500 | $45 | $75 | $90 | $400 | $15 | no |

# Members

| member_ref | name | DOB | plan | deductible met | OOP met |
|---|---|---|---|---|---|
| EVG-482913 | Maria Lopez | 1986-04-12 | Silver PPO | $850 | $1,200 |
| EVG-337120 | James Carter | 1979-11-02 | Gold HMO | $500 | $1,450 |
| EVG-559804 | Priya Nair | 1992-07-23 | Silver PPO | $300 | $410 |
| EVG-610277 | Robert Chen | 1958-01-30 | Gold HMO | $500 | $2,980 |
| EVG-725031 | Aisha Okafor | 1990-09-15 | Bronze EPO | $1,120 | $1,120 |
| EVG-801456 | Daniel Kim | 2001-03-08 | Silver PPO | $0 | $60 |

# Claims

| claim_id | member | service | provider | date | billed | status | plan paid | member owes | notes |
|---|---|---|---|---|---|---|---|---|---|
| C-20931 | Maria | Office visit – dermatology | Mission Dermatology | 2026-09-10 | $220 | paid (2026-09-28) | $185 | $35 | specialist copay |
| C-20977 | Maria | Lab work – lipid panel | Quest Diagnostics | 2026-09-18 | $140 | processing | — | — | decision expected 2026-10-10 |
| C-31544 | James | Emergency appendectomy | Lakeside Surgical Center | 2026-08-29 | $18,400 | denied | $0 | — | denial: out-of-network facility; appeal deadline 2027-02-25 |
| C-31602 | James | Emergency room visit | Bayview Medical Center | 2026-08-29 | $2,150 | paid (2026-09-15) | $1,950 | $200 | ER copay |
| C-40210 | Priya | MRI lumbar spine | Bay Imaging | 2026-09-22 | $1,850 | pending information | — | — | provider asked to send authorization number PA-77812 |
| C-41007 | Robert | Physical therapy, 6 visits | Harbor Physical Therapy | 2026-09-05 | $900 | paid (2026-09-25) | $660 | $240 | 6 × $40 specialist copay |
| C-52230 | Aisha | Urgent care visit | CityCare Urgent Care | 2026-09-30 | $310 | paid (2026-10-03) | $220 | $90 | urgent care copay |

# Prior authorizations (catalog endpoint only)

| auth_id | member | service | status | details |
|---|---|---|---|---|
| PA-77812 | Priya | MRI lumbar spine | approved | approved 2026-09-20, valid through 2026-12-20 |
| PA-77930 | Aisha | Knee arthroscopy | pending clinical review | decision expected 2026-10-09 |
| PA-78001 | Robert | CPAP device | denied | insufficient documentation; provider may resubmit with a sleep study |

# Providers (in-network)

| name | specialty | practice | zip | phone | new patients |
|---|---|---|---|---|---|
| Dr. Elena Ruiz | Dermatology | Mission Dermatology | 94110 | (415) 555-0110 | yes |
| Dr. Samuel Park | Dermatology | Sunset Skin Clinic | 94122 | (415) 555-0127 | no |
| Dr. Grace Liu | Primary care | Bayview Family Medicine | 94124 | (415) 555-0133 | yes |
| Dr. Marcus Bell | Orthopedics | Lakeside Orthopedics | 94115 | (415) 555-0148 | yes |
| Harbor Mental Health Associates | Behavioral health | Harbor Mental Health | 94103 | (415) 555-0156 | yes |
| Dr. Hannah Wright | Pediatrics | Little Steps Pediatrics | 94110 | (415) 555-0161 | yes |

Results for a zip sort exact zip matches first, then by name.

# Pharmacy (`evergreen-pharmacy`)

Formulary: atorvastatin — tier 1, $5, no PA · sertraline — tier 1, $5 · apixaban (Eliquis) — tier 2, $40 · semaglutide (Ozempic) — tier 3, $75, PA required, quantity limit 4 pens/28 days, alternatives: none · adalimumab (Humira) — specialty tier, $150, PA required.

Refills: RX-55102 (Maria, atorvastatin, 3 refills left, last fill 2026-09-20, next eligible 2026-10-15, Evergreen Mail Pharmacy) · RX-55170 (Robert, apixaban, 0 refills left — needs new prescription).

# Nurse line

24/7 nurse line: **1-800-555-0142** (fictional).
