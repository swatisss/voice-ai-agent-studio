---
type: Seed Data
title: Northgate members, policies, claims and pricing
description: The synthetic business records behind the mock API - products and the rating table, members, policies, payments, claims, pre-authorisations, specialists, cash plans, Digital GP slots, documents, underwriting rules and seeded memory.
status: stable
tags: [demo-data, mock, healthcare, uk]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

All records are fictional. Phone numbers use the Ofcom drama range (07700 900xxx); emails use `example.co.uk`. Dates written **T±n** are relative to the day the process starts or `seed --reset` runs; fixed dates are written out. The code lives in `voiceai/mock/data.py`; the endpoints are in [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md).

# Products

| Product | Factor | Covers |
|---|---|---|
| Northgate Complete | 1.00 | diagnosis and treatment: consultations, tests, scans, surgery, cancer care, mental health, therapies |
| Northgate Essentials | 0.70 | treatment once diagnosed; no outpatient diagnostics, so no outpatient limit |

**Options and factors**: outpatient limit (Complete only) unlimited 1.00 · £1,000 0.88 · £750 0.84 · £500 0.80; excess £0 1.00 · £100 0.94 · £250 0.87 · £500 0.78; hospital list Essential 0.85 (about 200 partner hospitals outside central London) · Extended 1.00 (about 300 across the UK, outside central London) · London Premium 1.20 (all recognised hospitals). **Add-ons** per person per month: dental and optical £11.50 · Therapies Plus £6.00 · travel cover £4.50.

**Age-band base** (monthly, Complete, Extended, unlimited outpatient, £0 excess): 0–17 £22 · 18–24 £38 · 25–29 £42 · 30–34 £48 · 35–39 £55 · 40–44 £64 · 45–49 £75 · 50–54 £89 · 55–59 £106 · 60–64 £128 · 65–69 £155 · 70+ £190. Age is taken on the cover start date.

**Region factor** by postcode area: London (EC, WC, E, N, NW, SE, SW, W) 1.25 · South East (BN, GU, RH, TN, OX, RG, SL, HP, KT, SM, CR, BR, TW, UB, HA, EN, IG, RM, DA, ME, CT, SO, PO) 1.10 · Scotland, North East, Wales and Northern Ireland (EH, G, AB, DD, KY, FK, PA, IV, NE, SR, DH, TS, CF, SA, NP, LL, BT) 0.90 · rest of England 1.00.

**Other factors**: smoker (nicotine in the last 12 months, age 16+) × 1.10; two people 5% off, three or more 10% off (core premium only); full medical underwriting × 0.95. Quotes are valid 14 days.

**Packages** shown with every quote: Essentials (Essentials, Essential list, £250 excess) · Balanced (Complete, £1,000 outpatient, £100 excess, Extended) · Complete (Complete, unlimited, £0 excess, Extended).

Example: two non-smokers aged 36 and 34 in Bristol (BS6) pay £50.65 (Essentials), £80.94 (Balanced) or £97.85 (Complete) a month.

# Members

| Member | Ref | Born | Lives | Holds | Story |
|---|---|---|---|---|---|
| Sarah Mitchell | NGH-410237 | 14 Mar 1984 | Leeds LS6 | `PMI-300101` Complete, family (Sarah, Ben, Isla), £100 excess, unlimited outpatient, Extended, moratorium, dental and optical add-on; renews T+45 | knee MRI paid under `PA-500812`; excess used this year; registered phone 07700 900141 |
| David Okoro | NGH-522918 | 2 Sep 1977 | Manchester M1 | `PMI-300214` Essentials, £250 excess, Essential list, full medical | this month's £61.20 Direct Debit failed: cover suspended, pay by T+19; £60 shortfall on `CL-70412`; knee replacement `PA-501020` approved; phone 07700 900142 |
| Emma Clarke | NGH-638405 | 21 Jun 1991 | Bristol BS6 | `PMI-300377` Complete, £100 excess, £1,000 outpatient (£640 used), Extended, moratorium (migraine excluded), Therapies Plus; `CSH-400204` cash plan Level 2 | shoulder arthroscopy `PA-500955` pending; physio claim `CL-70588` processing; cash plan claim `CC-81402` needs a receipt with her name; phone 07700 900143 |
| Raj Patel | NGH-714560 | 30 Nov 1966 | London N2 | `PMI-300452` Complete, £0 excess, unlimited, London Premium, full medical with "lower back conditions" excluded | back injection claim `CL-70640` declined (exclusion) |
| Tom Harris | NGH-805193 | 8 Jan 2000 | Birmingham B12 | `PMI-300519` Essentials, £250 excess, Essential list, moratorium; started T−10 | inside the 21-day cooling-off (ends T+11) |
| Lucy Evans | NGH-917362 | 17 May 1959 | Cardiff CF11 | `CSH-400118` cash plan Level 3 only | dental £145 claimed and paid (`CC-81204`); optical claim `CC-81377` £220 processing against a £200 limit; no Digital GP (cash plan only) |

Preferred contact: Sarah email, David phone after 6pm, Emma SMS.

# Policies and payments

Every policy is paid monthly by Direct Debit on the 1st; the next collection is the 1st of next month; the last three collections succeeded, except: David's latest collection failed (`missed`, £61.20, reinstate by T+19, account ending 0937) and Tom has no collections yet. Monthly premiums: Sarah £187.40, David £61.20, Emma £52.80 (+ £13.50 cash plan), Raj £168.90, Tom £29.60, Lucy £23.30. While a payment is missed the policy status is `payment_missed` and every cover check returns `covered: false`.

# Claims (health)

| Claim | Member | Service | Status | Paid / owed |
|---|---|---|---|---|
| CL-70231 | Sarah | Knee MRI scan, Headingley Park Imaging | paid | £550 to the hospital; £100 excess |
| CL-70412 | David | Orthopaedic consultation, Mr Alan Price | paid | £220; £60 shortfall (not fee-assured) |
| CL-70588 | Emma | Physiotherapy, 4 sessions | processing | decision T+3 |
| CL-70640 | Raj | Lumbar spine injection, St John's Wood Clinic | declined | lower back conditions excluded |

# Pre-authorisations

| Code | Member | Service | Status |
|---|---|---|---|
| PA-500812 | Sarah | Knee MRI scan, Mr James Holloway, Headingley Park Hospital | approved, valid to 15 Dec 2026 |
| PA-500955 | Emma | Shoulder arthroscopy | pending (procedure code and fee estimate), decision T+2 |
| PA-501020 | David | Knee replacement, Mr Alan Price, Didsbury Private Hospital | approved, valid to 25 Jan 2027 |

New codes start at `PA-502001`.

**Direct Access** (no GP referral): muscles, bones and joints (back, neck, knee, shoulder, hip pain, sports injury, joint, muscle, bone); mental health (anxiety, depression, stress, low mood, panic, insomnia); cancer symptoms (lump, unexplained weight loss, blood in…); skin (mole, skin lesion). Condition words map to a specialty: knee, hip, shoulder, back, neck, joint → orthopaedics; anxiety, depression, stress → psychiatry; skin, mole, rash → dermatology; heart, chest → cardiology; stomach, bowel, reflux → gastroenterology; lump, cancer, breast → oncology; ear, nose, throat, sinus → ENT; cataract, eye → ophthalmology.

# Specialists (Finder)

| Id | Name | Specialty | Hospital | Area | Lists | Fee-assured | First available |
|---|---|---|---|---|---|---|---|
| CN-101 | Mr James Holloway | orthopaedics | Headingley Park Hospital | LS | all | yes | T+6 |
| CN-102 | Ms Priya Desai | orthopaedics | Roundhay Private Hospital | LS | Extended, London Premium | yes | T+9 (video) |
| CN-103 | Mr Alan Price | orthopaedics | Didsbury Private Hospital | M | Extended, London Premium | **no** | T+4 |
| CN-104 | Dr Fiona Grant | orthopaedics | Bath Abbey Clinic | BS | all | yes | T+5 (video) |
| CN-105 | Mr Oliver Reed | orthopaedics | Clifton Downs Hospital | BS | Extended, London Premium | yes | T+8 |
| CN-106 | Mr Daniel Shaw | orthopaedics | St John's Wood Hospital | NW | London Premium | yes | T+3 |
| CN-201 | Dr Helen Moss | dermatology | Headingley Park Hospital | LS | all | yes | T+7 (video) |
| CN-202 | Dr Kwame Asante | dermatology | Harley Court Clinic | W | London Premium | yes | T+4 (video) |
| CN-301 | Dr Laura Bennett | psychiatry | Redland House Hospital | BS | all | yes | T+5 (video) |
| CN-302 | Dr Samir Haddad | psychiatry | Northgate Mind Clinic, Manchester | M | all | yes | T+3 (video) |
| CN-401 | Dr Rachel Kim | cardiology | Roundhay Private Hospital | LS | Extended, London Premium | yes | T+10 |
| CN-501 | Mr Thomas Wright | gastroenterology | Didsbury Private Hospital | M | Extended, London Premium | yes | T+8 (video) |
| CN-601 | Dr Anika Sharma | oncology | Harley Court Clinic | W | all | yes | T+2 |
| CN-602 | Dr Mark Ellis | oncology | Headingley Park Hospital | LS | all | yes | T+2 |
| CN-701 | Ms Claire Douglas | ENT | Clifton Downs Hospital | BS | Extended, London Premium | yes | T+9 (video) |
| CN-801 | Mr Peter Lang | ophthalmology | Didsbury Private Hospital | M | all | yes | T+12 |

# Cash plan

Yearly limits (100% refunded up to the limit): dental £200 / £300 / £400 · optical £60 / £120 / £200 · therapies £100 / £200 / £300 · consultations £150 / £250 / £350 · hospital nights £400 / £600 / £800 for Levels 1 / 2 / 3. Claims online within 6 months with a receipt showing the patient's name, the provider, the date and the cost; paid within 5 working days.

# Digital GP

Twelve slots: for each of the next three days, 9:00 GP video, 12:00 nurse phone, 18:00 GP phone, 20:00 GP video; slot ids `GP-<day><hour>` (for example `GP-109` is tomorrow at 9:00). Available to anyone named on a health policy; not with a cash plan only.

# Documents

Health: membership certificate, policy guide, digital membership card, premium statement. Cash plan: policy guide, membership card, premium statement, table of benefits. Delivery: email within 15 minutes, sms link within 5 minutes, post in 5 to 7 working days.

# Underwriting

Moratorium (no questions; conditions in the 5 years before cover are excluded until 2 clear years), full medical underwriting (answers for everyone; personal exclusions; 5% cheaper; serious conditions refer to an underwriter), switch (keeps another UK insurer's terms after 12 months of continuous cover). Scoring and referral rules are in [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md).

# Seeded memory

On the Customer Care agent ([/architecture/agent-memory.md](/architecture/agent-memory.md)): Sarah Mitchell — facts "Prefers documents by email" (preference) and "Her husband Ben and daughter Isla are on her policy" (relationship), and the episode "Asked whether her knee MRI was paid; the agent explained the hospital was paid directly and only the £100 excess was hers to pay." David Okoro — fact "Prefers a call back after 6pm" and one episode about the £60 shortfall. On Claims & Pre-authorisation: Emma Clarke — fact "Waiting for a shoulder arthroscopy pre-authorisation" (circumstance).
