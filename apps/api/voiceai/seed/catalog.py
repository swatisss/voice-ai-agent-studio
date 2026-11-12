"""Seed definitions: tenants, personas, tools, skills, agents, use cases, regression scenarios (Northgate Health).

Spec: /demo-data/northgate-health.md, /product/use-cases.md
"""
from __future__ import annotations

from typing import Any

CARE_TENANT = "northgate-health"
SANDBOX_TENANT = "northgate-sandbox"

TENANTS = [
    {"id": CARE_TENANT, "name": "Northgate Health · Member & Sales Services", "industry": "Health insurance"},
    {"id": SANDBOX_TENANT, "name": "Northgate Health · Sandbox", "industry": "Health insurance"},
]

_EMPTY: dict[str, Any] = {"type": "object", "properties": {}}
DISCLOSURE = "I'm a virtual assistant, and this call may be recorded for quality and training."


def _params(required: list[str] | None = None, **props: str) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()}, "required": required or []}


def _tool(name: str, description: str, method: str, url: str, parameters: dict[str, Any] | None = None, verify: bool = False) -> dict[str, Any]:
    return {"name": name, "description": description, "method": method, "url": url, "parameters": parameters or _EMPTY, "requires_verification": verify}


_POLICY = "Policy number like PMI-300101 (health) or CSH-400118 (cash plan)"

# ---- tools (24): verify = requires_verification
TOOLS: list[dict[str, Any]] = [
    {"name": "verify_member", "description": "Verify the caller's identity with their membership number and date of birth. Required before any member-specific information.",
     "method": "POST", "url": "/mock/healthcare/verify",
     "parameters": _params(["member_id", "date_of_birth"], member_id="Membership number as spoken, e.g. 410237 or NGH-410237", date_of_birth="Date of birth in YYYY-MM-DD format"),
     "requires_verification": False, "is_verification": True},
    # Customer Care
    _tool("get_member_policies", "List the verified member's policies: policy number, type (health or cash_plan), product, status, start and renewal date.",
          "GET", "/mock/insurance/policies", verify=True),
    _tool("get_policy_details", "One policy of the verified member: status, monthly premium, payment status, who is covered, excess, outpatient limit, hospital list, underwriting, add-ons and cooling-off date.",
          "GET", "/mock/insurance/policies/{policy_id}", _params(["policy_id"], policy_id=_POLICY), verify=True),
    _tool("get_payments", "Direct Debit details of a policy: status, monthly amount, collection day, next collection date, recent payments, any missed amount and the date to pay it by.",
          "GET", "/mock/insurance/policies/{policy_id}/payments", _params(["policy_id"], policy_id=_POLICY), verify=True),
    _tool("retry_missed_payment", "Collect a missed premium again by Direct Debit on a chosen date (at least 3 days ahead, before the reinstate-by date).",
          "POST", "/mock/insurance/policies/{policy_id}/payments/retry",
          _params(["policy_id"], policy_id=_POLICY, collect_on="Date to collect, YYYY-MM-DD; leave out for the earliest date"), verify=True),
    _tool("change_collection_day", "Change the day of the month the Direct Debit is collected (1 to 28).",
          "POST", "/mock/insurance/policies/{policy_id}/payments/collection-day",
          {"type": "object", "properties": {"policy_id": {"type": "string", "description": _POLICY},
                                            "day": {"type": "integer", "description": "Day of the month, 1 to 28"}}, "required": ["policy_id", "day"]}, verify=True),
    _tool("update_contact_details", "Change the verified member's email address, UK mobile number or postal address (with postcode). Never bank details.",
          "POST", "/mock/insurance/members/me/contact",
          _params([], email="New email address", mobile="New UK mobile number", address="New postal address including the postcode"), verify=True),
    _tool("send_secure_link", "Send a secure link by sms or email to change bank details, set up a Direct Debit or pay a missed premium by card. Bank and card details are never taken on the call.",
          "POST", "/mock/insurance/secure-links",
          _params(["purpose", "channel"], purpose="change_bank_details, direct_debit_setup or make_payment", channel="sms or email", policy_id=_POLICY), verify=True),
    _tool("list_documents", "Documents that can be sent for a policy.", "GET", "/mock/insurance/documents",
          _params(["policy_id"], policy_id=_POLICY), verify=True),
    _tool("request_document", "Send a policy document by email, sms (a link) or post.", "POST", "/mock/insurance/documents/request",
          _params(["policy_id", "document_type", "delivery"], policy_id=_POLICY,
                  document_type="membership_certificate, policy_guide, membership_card, premium_statement or table_of_benefits",
                  delivery="email, sms or post"), verify=True),
    _tool("get_gp_slots", "Free Digital GP appointments (video or phone) for members with health insurance.", "GET", "/mock/healthcare/gp/slots",
          _params([], type="gp or nurse (advanced nurse practitioner)", format="video or phone"), verify=True),
    _tool("book_gp_appointment", "Book a Digital GP appointment from get_gp_slots for someone covered on the member's health policy.",
          "POST", "/mock/healthcare/gp/appointments",
          _params(["slot_id", "reason"], slot_id="Slot like GP-109", reason="Short reason for the appointment, in the caller's words",
                  patient_name="Name of the person the appointment is for, if not the caller"), verify=True),
    _tool("get_cash_plan_benefits", "Cash plan limits for the year: each benefit's limit, what is used and what is left, and how to claim.",
          "GET", "/mock/insurance/policies/{policy_id}/cash-benefits", _params(["policy_id"], policy_id="Cash plan number like CSH-400118"), verify=True),
    _tool("get_cash_plan_claims", "The verified member's cash plan claims (number, benefit, provider, date, status).", "GET", "/mock/insurance/cash-plan/claims", verify=True),
    _tool("get_cash_plan_claim", "One cash plan claim by number (e.g. CC-81204): status, amount paid, date and any notes.",
          "GET", "/mock/insurance/cash-plan/claims/{claim_id}", _params(["claim_id"], claim_id="Cash plan claim number like CC-81204"), verify=True),
    # Claims & Pre-authorisation
    _tool("check_treatment_cover", "Check whether a condition and treatment are covered on the member's health policy: exclusions, moratorium, product rules, "
          "whether a GP referral is needed (Direct Access), the specialty, excess left, outpatient limit left and forms needed.",
          "GET", "/mock/insurance/policies/{policy_id}/eligibility",
          _params(["policy_id", "condition"], policy_id="Health policy number like PMI-300101", condition="The condition or symptoms in plain words, e.g. knee pain",
                  treatment="The treatment or test, e.g. consultation, MRI scan, knee arthroscopy"), verify=True),
    _tool("find_specialists", "Find up to three recognised consultants (Finder) on the member's hospital list, nearest first; says if each is fee-assured.",
          "GET", "/mock/healthcare/specialists",
          _params([], specialty="e.g. orthopaedics, dermatology, psychiatry, cardiology", condition="Or the condition, to work out the specialty",
                  postcode="The caller's postcode", policy_id="Health policy number, to use the member's hospital list")),
    _tool("create_pre_authorisation", "Issue a pre-authorisation code for covered treatment so the hospital or specialist bills us directly. "
          "Surgery stays pending until the specialist sends the procedure code.",
          "POST", "/mock/healthcare/pre-authorisations",
          _params(["policy_id", "condition", "treatment", "symptoms_started"], policy_id="Health policy number like PMI-300101",
                  condition="The condition", treatment="The consultation, test or treatment recommended",
                  referral="open_referral, named_referral, direct_access or none", specialist_id="Specialist id from find_specialists, e.g. CN-101",
                  symptoms_started="When symptoms first started, in the caller's words or YYYY-MM-DD", gp_first_seen="When the GP was first seen, if they were",
                  patient_name="Who the treatment is for, if not the caller"), verify=True),
    _tool("get_pre_authorisation", "Status of a pre-authorisation by code (e.g. PA-500812): approved, pending or declined, what it covers and until when.",
          "GET", "/mock/healthcare/prior-auths/{auth_id}", _params(["auth_id"], auth_id="Pre-authorisation code like PA-500812"), verify=True),
    _tool("get_member_claims", "The verified member's health insurance claims (number, service, date, status).", "GET", "/mock/healthcare/claims", verify=True),
    _tool("get_claim_status", "One health claim by number (e.g. CL-70231): status, what we paid, what the member owes (excess or shortfall), decline reason and next step.",
          "GET", "/mock/healthcare/claims/{claim_id}", _params(["claim_id"], claim_id="Claim number like CL-70231"), verify=True),
    # Health Cover Sales (no identity check: callers are not members yet)
    _tool("create_quote", "Start a health insurance quote for up to 6 people: returns three packages (Essentials, Balanced, Complete) with monthly prices.",
          "POST", "/mock/sales/quotes",
          {"type": "object", "properties": {
              "people": {"type": "array", "description": "Everyone to cover, the policyholder first",
                         "items": {"type": "object", "properties": {
                             "name": {"type": "string", "description": "Full name"},
                             "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
                             "smoker": {"type": "boolean", "description": "Smoked or used nicotine in the last 12 months"},
                             "relationship": {"type": "string", "description": "policyholder, partner or child"}},
                             "required": ["date_of_birth"]}},
              "postcode": {"type": "string", "description": "Full UK postcode of the policyholder"},
              "start_date": {"type": "string", "description": "When cover should start, YYYY-MM-DD, today to 90 days ahead"},
              "occupation": {"type": "string", "description": "The policyholder's occupation"},
          }, "required": ["people", "postcode"]}),
    _tool("price_quote", "Price the cover the caller chooses on a quote: a package, or product, outpatient limit, excess, hospital list and add-ons.",
          "POST", "/mock/sales/quotes/{quote_id}/price",
          {"type": "object", "properties": {
              "quote_id": {"type": "string", "description": "Quote reference like Q-60001"},
              "package": {"type": "string", "description": "essentials, balanced or complete, as a starting point"},
              "product": {"type": "string", "description": "complete or essentials"},
              "outpatient_limit": {"type": "string", "description": "Complete only: unlimited, 1000, 750 or 500"},
              "excess": {"type": "integer", "description": "0, 100, 250 or 500"},
              "hospital_list": {"type": "string", "description": "essential, extended or london_premium"},
              "add_ons": {"type": "array", "items": {"type": "string"}, "description": "dental_optical, therapies_plus, travel_cover"},
          }, "required": ["quote_id"]}),
    _tool("assess_underwriting", "Underwrite the priced quote: moratorium (no medical questions), full_medical (health answers for everyone; gives exclusions) or switch "
          "(keep terms from another UK insurer after 12+ months). Returns a risk score, the decision and the final monthly price.",
          "POST", "/mock/sales/quotes/{quote_id}/underwriting",
          {"type": "object", "properties": {
              "quote_id": {"type": "string", "description": "Quote reference like Q-60001"},
              "method": {"type": "string", "description": "moratorium, full_medical or switch"},
              "answers": {"type": "array", "description": "full_medical: one entry per person",
                          "items": {"type": "object", "properties": {
                              "person": {"type": "string", "description": "The person's name"},
                              "conditions": {"type": "array", "items": {"type": "string"}, "description": "Conditions with symptoms, treatment, medication or advice in the last 5 years; empty if none"},
                              "hazardous_activities": {"type": "boolean", "description": "Semi-professional or professional sport, or other hazardous pursuits"}}}},
              "previous_insurer": {"type": "string", "description": "switch: the current UK insurer"},
              "continuous_cover_months": {"type": "integer", "description": "switch: months of continuous cover"},
          }, "required": ["quote_id", "method"]}),
    _tool("create_policy", "Create the policy after the key facts and declaration are read and confirmed: returns the policy and membership numbers, start date and first "
          "collection; sends the documents and a secure Direct Debit link by email or sms.",
          "POST", "/mock/sales/applications",
          {"type": "object", "properties": {
              "quote_id": {"type": "string", "description": "Quote reference"},
              "underwriting_id": {"type": "string", "description": "From assess_underwriting, like UW-70001"},
              "policyholder": {"type": "object", "properties": {
                  "first_name": {"type": "string"}, "last_name": {"type": "string"}, "email": {"type": "string"},
                  "mobile": {"type": "string", "description": "UK mobile starting 07"}, "address": {"type": "string", "description": "Postal address with postcode"}},
                  "required": ["first_name", "last_name", "email", "mobile", "address"]},
              "documents_by": {"type": "string", "description": "email or sms"},
              "payment_link_by": {"type": "string", "description": "email or sms: where to send the Direct Debit set-up link"},
              "key_facts_confirmed": {"type": "boolean", "description": "True only after the key facts were read and the caller said yes"},
              "declaration_confirmed": {"type": "boolean", "description": "True only after the declaration was read and the caller agreed"},
              "marketing_opt_in": {"type": "boolean", "description": "Only if the caller asked for offers"},
          }, "required": ["quote_id", "underwriting_id", "policyholder", "key_facts_confirmed", "declaration_confirmed"]}),
]

# ---- skills
_VERIFY = {
    "name": "Identity verification",
    "description": "Any request about the caller's own policy, payments, claims, pre-authorisations, documents or appointments.",
    "instructions": (
        "1. Ask for the caller's membership number and date of birth.\n"
        "2. Call verify_member with the membership number and the date of birth in YYYY-MM-DD format.\n"
        "3. If verified, thank them by first name and continue. If not, ask them to repeat both once.\n"
        "4. Never read back the full membership number or date of birth."),
    "required_tools": ["verify_member"], "escalate_when": "Verification fails twice.",
}

CARE_SKILLS: list[dict[str, Any]] = [
    _VERIFY,
    {"name": "Policy and cover questions", "description": "What the caller's policy includes: who is covered, excess, outpatient limit, hospital list, add-ons, renewal date.",
     "instructions": (
         "1. For general questions on how cover works, call search_knowledge.\n"
         "2. For the caller's own policy: verify, call get_member_policies, then get_policy_details.\n"
         "3. Answer with the specific detail asked for, in one or two sentences.\n"
         "4. If they want treatment approved, a consultant or a claim status, say the claims team handles it and transfer."),
     "required_tools": ["verify_member", "get_member_policies", "get_policy_details"],
     "escalate_when": "The caller wants to change cover mid-term, or disputes the terms of the policy."},
    {"name": "Payments and Direct Debit", "description": "Premiums, collection dates, missed or failed payments, changing the collection day or bank account.",
     "instructions": (
         "1. Verify, find the policy, then call get_payments.\n"
         "2. Say the status, the monthly amount and the next collection date.\n"
         "3. If a payment was missed: explain cover is suspended until it is paid and the date to pay by; offer retry_missed_payment, "
         "or send_secure_link with purpose make_payment to pay by card.\n"
         "4. To change the collection day, call change_collection_day.\n"
         "5. To change bank details, call send_secure_link with purpose change_bank_details. Never take bank or card details on the call."),
     "required_tools": ["verify_member", "get_member_policies", "get_payments", "retry_missed_payment", "send_secure_link"],
     "escalate_when": "The caller disputes a charge or asks for a refund."},
    {"name": "Update contact details", "description": "Change email address, mobile number or postal address.",
     "instructions": (
         "1. Verify first.\n"
         "2. Take the new detail, read it back and wait for a yes.\n"
         "3. Call update_contact_details and say where the confirmation went.\n"
         "4. For a change of name, adding an adult or removing someone from the policy, transfer to a person."),
     "required_tools": ["verify_member", "update_contact_details"], "escalate_when": "Adding an adult, removing someone, or a change of name."},
    {"name": "Documents and membership card", "description": "Membership certificate, policy guide, membership card, premium statement, cash plan table of benefits.",
     "instructions": (
         "1. Verify, find the policy with get_member_policies, then call list_documents.\n"
         "2. Confirm which document and how to send it: email, sms link or post.\n"
         "3. Call request_document and say when it arrives, without reading out the address."),
     "required_tools": ["verify_member", "get_member_policies", "list_documents", "request_document"], "escalate_when": ""},
    {"name": "Book a Digital GP appointment", "description": "Video or phone appointment with a GP or advanced nurse practitioner.",
     "instructions": (
         "1. If the caller describes an emergency (chest pain, difficulty breathing, signs of a stroke, heavy bleeding), tell them to call 999 now and stop.\n"
         "2. Verify, then ask who the appointment is for, GP or nurse, and video or phone.\n"
         "3. Call get_gp_slots and offer up to three times.\n"
         "4. Read the chosen time back, then call book_gp_appointment with a short reason in the caller's words.\n"
         "5. Give the booking reference and how to join. Mention the 24-hour nurse line for advice before then."),
     "required_tools": ["verify_member", "get_gp_slots", "book_gp_appointment"], "escalate_when": ""},
    {"name": "Cash plan", "description": "Cash plan limits, what is left, how to claim and the status of cash plan claims.",
     "instructions": (
         "1. Verify and find the cash plan with get_member_policies.\n"
         "2. For limits, call get_cash_plan_benefits and give the limit, used and remaining for the benefit asked about.\n"
         "3. For a claim, ask for the claim number or call get_cash_plan_claims, then get_cash_plan_claim.\n"
         "4. To make a claim, explain it is done online with a receipt showing the patient's name, the provider, the date and the cost."),
     "required_tools": ["verify_member", "get_member_policies", "get_cash_plan_benefits", "get_cash_plan_claims", "get_cash_plan_claim"],
     "escalate_when": "The caller disputes a cash plan claim decision."},
    {"name": "Renewal, cancellation, complaints and bereavement", "description": "Renewal questions, cancelling, making a complaint, or telling us a member has died.",
     "instructions": (
         "1. For how renewal, cooling-off or cancellation work, call search_knowledge and explain briefly.\n"
         "2. A caller who wants to cancel: verify, check cooling_off_ends with get_policy_details, explain the refund rules, then hand over to a person.\n"
         "3. A complaint: acknowledge it, summarise it in one sentence, then hand over with reason policy_required.\n"
         "4. A bereavement: offer condolences first, keep it brief and gentle, then hand over to the bereavement team."),
     "required_tools": ["verify_member", "get_policy_details"], "escalate_when": "Always for cancellation, complaints and bereavement."},
]

CLAIMS_SKILLS: list[dict[str, Any]] = [
    _VERIFY,
    {"name": "Get treatment approved (pre-authorisation)", "description": "The member has symptoms, has seen a GP or has a referral and wants treatment covered.",
     "instructions": (
         "1. If the caller describes an emergency, tell them to call 999 or go to A&E now and stop.\n"
         "2. Verify, find the health policy with get_member_policies.\n"
         "3. Ask one at a time: the condition or symptoms, when they started, whether a GP has seen them and what treatment or test was recommended.\n"
         "4. Call check_treatment_cover. If not covered, explain the reason plainly and stop.\n"
         "5. If a GP referral is needed and they have none, explain the open referral and offer a Digital GP appointment through member services.\n"
         "6. Call find_specialists with the condition, their postcode and the policy, and offer the options; mention fee-assured specialists mean no shortfall.\n"
         "7. Read back the condition, treatment and specialist, then call create_pre_authorisation.\n"
         "8. Read the code slowly, say what it covers, the excess to pay and any forms needed."),
     "required_tools": ["verify_member", "get_member_policies", "check_treatment_cover", "find_specialists", "create_pre_authorisation"],
     "escalate_when": "Cover depends on a clinical decision, or the treatment is not covered and the caller disagrees."},
    {"name": "Find a consultant or hospital", "description": "The member has a referral and wants a recognised specialist near them.",
     "instructions": (
         "1. Verify and find the health policy.\n"
         "2. Ask for the type of specialist (or the condition) and their postcode.\n"
         "3. Call find_specialists and offer up to three, with the hospital, first available date, video or phone option and whether they are fee-assured."),
     "required_tools": ["verify_member", "get_member_policies", "find_specialists"], "escalate_when": "No recognised specialist is on their hospital list."},
    {"name": "Pre-authorisation and claim status", "description": "Where a pre-authorisation or a claim stands.",
     "instructions": (
         "1. Verify first.\n"
         "2. For a pre-authorisation code, call get_pre_authorisation; for a claim number, call get_claim_status; without a number, call get_member_claims.\n"
         "3. Give the status, what we paid and what the member owes (excess or shortfall), and the next step."),
     "required_tools": ["verify_member", "get_pre_authorisation", "get_member_claims", "get_claim_status"],
     "escalate_when": "The caller disputes a declined claim or a shortfall."},
    {"name": "Excess, shortfalls and invoices", "description": "Why the member was billed, what the excess or a shortfall is, and where invoices go.",
     "instructions": (
         "1. For how excess and shortfalls work, call search_knowledge.\n"
         "2. For a specific bill, verify and look up the claim with get_claim_status.\n"
         "3. Explain in plain words: the excess is paid once per person per policy year; a shortfall is what a consultant charges above our fee guidelines."),
     "required_tools": ["verify_member", "get_claim_status"], "escalate_when": "The caller disputes an amount."},
]

SALES_SKILLS: list[dict[str, Any]] = [
    {"name": "Health insurance quote", "description": "A new customer wants a price for health insurance for themselves, a partner or the family.",
     "instructions": (
         "1. Ask one thing at a time: who to cover, each person's name and date of birth, whether anyone smoked in the last 12 months, "
         "the policyholder's postcode, and when cover should start.\n"
         "2. Call create_quote.\n"
         "3. Present the three packages in one short sentence each with the monthly price, cheapest first, and ask what matters most to them."),
     "required_tools": ["create_quote"], "escalate_when": "The caller wants cover for a business or more than 6 people."},
    {"name": "Choose and customise cover", "description": "The caller compares options: product, outpatient limit, excess, hospital list, add-ons.",
     "instructions": (
         "1. Explain one option at a time in plain words (search_knowledge for details).\n"
         "2. After each change call price_quote and give the new monthly price and how it compares.\n"
         "3. Do not recommend a product: give facts and let the caller choose. Say this is not advice if they ask which is best."),
     "required_tools": ["price_quote"], "escalate_when": "The caller asks for personal advice on which cover to buy."},
    {"name": "Underwriting questions", "description": "After the caller has chosen cover: how medical history is handled.",
     "instructions": (
         "1. Explain moratorium, full medical underwriting and switching in one sentence each and ask which they prefer.\n"
         "2. Full medical: for each person ask whether they have had symptoms, treatment, medication or advice for any condition in the last 5 years, "
         "and about professional or hazardous sports.\n"
         "3. Switch: ask for the current insurer and how many months of continuous cover.\n"
         "4. Call assess_underwriting. Read every exclusion and the final monthly price. If referred to an underwriter, hand over to a person."),
     "required_tools": ["assess_underwriting"], "escalate_when": "The decision is refer_to_underwriter."},
    {"name": "Join and register", "description": "The caller wants to go ahead and buy the policy.",
     "instructions": (
         "1. Collect the policyholder's full name, email, UK mobile and postal address; read them back.\n"
         "2. Read the key facts: the cover chosen, the excess, any exclusions, the monthly price, that the 21-day cooling-off gives a full refund if no claim is made. Ask: is that all correct?\n"
         "3. Read the declaration: the information given is true and complete to the best of their knowledge. Ask if they agree.\n"
         "4. Ask whether documents and the Direct Debit link go by email or text.\n"
         "5. Only after two clear yeses call create_policy with key_facts_confirmed and declaration_confirmed true.\n"
         "6. Give the policy number and membership number slowly, the start date and that the Direct Debit link must be used within 7 days."),
     "required_tools": ["create_policy"], "escalate_when": "The caller is unsure, seems to be under pressure, or does not understand the key facts."},
]

# ---- persona library
PERSONAS: list[dict[str, Any]] = [
    {"name": "Olivia", "description": "Warm, calm and concise; member services and the front desk.", "voice": "aura-2-pandora-en", "speed": 1.0,
     "greeting": "Thanks for calling Northgate Health, this is Olivia.", "disclosure": f"{DISCLOSURE} How can I help you today?", "opening": "",
     "style": "Warm, calm and concise. British English. One question at a time. Plain language, no insurance jargon unless the caller uses it."},
    {"name": "James", "description": "Clear and friendly; new customers and quotes. Never pushy.", "voice": "aura-2-draco-en", "speed": 1.0,
     "greeting": "Thanks for calling Northgate Health, this is James from the health insurance team.", "disclosure": f"{DISCLOSURE} Are you looking for a quote today?", "opening": "",
     "style": "Clear, friendly and patient. British English. Explains options as facts, never pushes, says prices slowly and checks understanding."},
    {"name": "Hannah", "description": "Calm and precise; claims and pre-authorisation. Reads codes and dates slowly.", "voice": "aura-2-pandora-en", "speed": 0.95,
     "greeting": "Thank you for calling Northgate Health claims, this is Hannah.", "disclosure": f"{DISCLOSURE} How can I help with your treatment?", "opening": "",
     "style": "Calm, precise and reassuring. British English. Acknowledge how the caller feels before facts. Read codes, dates and amounts slowly and confirm before acting."},
]

# ---- agents
_STD_NEVER = ["Promise that treatment or a claim will be paid before a pre-authorisation is issued.", "Share information about anyone other than the verified member and the people on their policy."]
_TD = {"mode": "semantic", "min_silence_ms": 700, "max_extra_wait_ms": 1500, "evaluator": "heuristic", "allow_interruptions": True}

AGENTS: list[dict[str, Any]] = [
    {
        "key": "care", "name": "Customer Care", "mode": "inbound", "persona": "Olivia", "kb": "customer-care",
        "description": "Member help and support for Northgate Health: policy and cover questions, payments and Direct Debit, contact details, documents, "
                       "Digital GP appointments, cash plan limits and claims, renewal, cancellation, complaints and bereavement.",
        "turn_detection": _TD,
        "tools": ["verify_member", "get_member_policies", "get_policy_details", "get_payments", "retry_missed_payment", "change_collection_day",
                  "update_contact_details", "send_secure_link", "list_documents", "request_document", "get_gp_slots", "book_gp_appointment",
                  "get_cash_plan_benefits", "get_cash_plan_claims", "get_cash_plan_claim"],
        "skills": CARE_SKILLS,
        "policy": {
            "rules": [
                "Verify identity with the membership number and date of birth before sharing any policy, payment, claim or document information.",
                "Never take bank account or card details on the call: send a secure link instead.",
                "Read every new contact detail back before saving it.",
                "For treatment approval, consultants or health claim status, transfer to the claims team; for a new quote, transfer to the health insurance team.",
                "If the caller describes a medical emergency, tell them to call 999.",
            ],
            "escalate_when": [
                "The caller wants to make a complaint.",
                "The caller wants to cancel a policy.",
                "The caller tells us a member has died.",
                "The caller wants to add an adult to the policy, remove someone, or change cover mid-term.",
                "The caller disputes a charge or a cash plan decision.",
            ],
            "never": [*_STD_NEVER, "Ask for or repeat bank account, sort code or card numbers."], "max_turns": 18,
            "handoff_message": "I'm connecting you with a colleague who will have all the details, so you won't need to repeat yourself.",
        },
    },
    {
        "key": "sales", "name": "Health Cover Sales", "mode": "inbound", "persona": "James", "kb": "sales",
        "description": "New customers: health insurance quotes for individuals, couples and families, comparing cover options, underwriting questions "
                       "and joining by phone, with documents and the Direct Debit link sent by email or text.",
        "turn_detection": _TD,
        "tools": ["create_quote", "price_quote", "assess_underwriting", "create_policy"],
        "skills": SALES_SKILLS,
        "policy": {
            "rules": [
                "This is a non-advised sale: give facts about the options and let the caller choose; never recommend a product.",
                "Collect one detail at a time and read personal details back before using them.",
                "Before create_policy, read the key facts and the declaration and get a clear yes to each.",
                "Mention the 21-day cooling-off period before the caller buys.",
                "Never take bank or card details: the Direct Debit is set up with a secure link.",
            ],
            "escalate_when": [
                "The underwriting decision is refer_to_underwriter.",
                "The caller asks for advice on which policy is right for them.",
                "The caller seems confused, vulnerable or under pressure from someone else.",
                "The caller wants business or group cover.",
            ],
            "never": ["Pressure the caller or say an offer ends today.", "Compare Northgate with named competitors.", "Give medical advice."],
            "max_turns": 30,
            "handoff_message": "I'll pass you to one of our health insurance specialists, who will have your quote in front of them.",
        },
    },
    {
        "key": "claims", "name": "Claims & Pre-authorisation", "mode": "inbound", "persona": "Hannah", "kb": "claims",
        "description": "Existing members getting treatment covered: checking cover for a condition, Direct Access or GP open referral, finding a recognised "
                       "consultant or hospital, issuing pre-authorisation codes so hospitals bill us directly, claim status, excess and shortfalls.",
        "turn_detection": _TD,
        "tools": ["verify_member", "get_member_policies", "check_treatment_cover", "find_specialists", "create_pre_authorisation",
                  "get_pre_authorisation", "get_member_claims", "get_claim_status"],
        "skills": CLAIMS_SKILLS,
        "policy": {
            "rules": [
                "Verify identity with the membership number and date of birth before any cover check, pre-authorisation or claim detail.",
                "Always call check_treatment_cover before issuing a pre-authorisation.",
                "Read pre-authorisation codes, claim numbers, dates and amounts slowly, and read details back before acting.",
                "If the caller describes a medical emergency, tell them to call 999 or go to A&E.",
            ],
            "escalate_when": [
                "The caller disputes a declined claim, an exclusion or a shortfall.",
                "Cover depends on a clinical decision the tools cannot make.",
                "The caller is distressed about a cancer diagnosis and wants to talk to a person.",
                "The caller asks for a person.",
            ],
            "never": ["Give medical advice or say which treatment is best.", "Discuss another member's claim.", "Say surgery is approved while the pre-authorisation is pending."],
            "max_turns": 20,
            "handoff_message": "I'm connecting you with a claims specialist who will have all the details, so you won't need to repeat yourself.",
            "holding_message": "A claims specialist will be with you shortly. Thanks for your patience.",
        },
    },
]

SANDBOX_KB = "sandbox"


# ---- test scenarios (/demo-data/northgate-health.md "Regression scenarios", /architecture/test-suites.md)
def _profile(name: str, member_id: str, dob: str, **extra: str) -> dict[str, str]:
    return {"name": name, "member_id": member_id, "date_of_birth": dob, **extra}


def _expect(name: str, **args: str) -> dict[str, Any]:
    return {"name": name, "args": args}


SCENARIOS = [  # Customer Care
    {"name": "Policy cover", "caller_goal": "You want to know your excess and which hospital list your policy has.",
     "caller_profile": _profile("Sarah Mitchell", "410237", "1984-03-14"), "expected": "resolved",
     "required_tools": [_expect("verify_member")]},
    {"name": "Missed payment", "caller_goal": "Your Direct Debit failed this month; you want it taken again and to know if you are still covered.",
     "caller_profile": _profile("David Okoro", "522918", "1977-09-02"), "expected": "resolved",
     "required_tools": [_expect("get_payments", policy_id="PMI-300214"), _expect("retry_missed_payment", policy_id="PMI-300214")]},
    {"name": "Digital GP for my daughter", "caller_goal": "You want a video GP appointment tomorrow for your daughter Isla, who has an ear infection.",
     "caller_profile": _profile("Sarah Mitchell", "410237", "1984-03-14", patient="Isla Mitchell"), "persona": "impatient", "expected": "resolved",
     "required_tools": [_expect("book_gp_appointment")]},
    {"name": "Cash plan optical limit", "caller_goal": "You want to know how much optical cover is left on your cash plan and why your glasses claim was not paid in full.",
     "caller_profile": _profile("Lucy Evans", "917362", "1959-05-17"), "persona": "confused", "expected": "resolved",
     "required_tools": [_expect("get_cash_plan_benefits", policy_id="CSH-400118")]},
    {"name": "Membership certificate by email", "caller_goal": "You want your membership certificate emailed to you.",
     "caller_profile": _profile("Raj Patel", "714560", "1966-11-30"), "expected": "resolved",
     "required_tools": [_expect("request_document", document_type="membership_certificate", delivery="email")],
     "expected_results": [{"tool": "request_document", "field": "status", "equals": "queued"}]},
    {"name": "Complaint", "caller_goal": "You are unhappy with how long your claim took and want to make a formal complaint.",
     "caller_profile": _profile("Raj Patel", "714560", "1966-11-30"), "expected": "escalated"},
    {"name": "Wrong date of birth first", "caller_goal": "You want to change the email address on your account.",
     "caller_profile": _profile("Emma Clarke", "638405", "1991-06-21", new_email="emma.c@example.co.uk"), "persona": "adversarial", "expected": "resolved",
     "required_tools": [_expect("verify_member"), _expect("update_contact_details")]},
    {"name": "Remembers email preference", "caller_goal": "You want your membership card sent to you.",
     "caller_profile": _profile("Sarah Mitchell", "410237", "1984-03-14"), "expected": "resolved", "memory": ["Prefers documents by email"],
     "required_tools": [_expect("request_document", document_type="membership_card", delivery="email")]},
]

CLAIMS_SCENARIOS = [
    {"name": "Knee pain, Direct Access", "caller_goal": "Your knee has hurt for three weeks; you want to see an orthopaedic specialist near Leeds without going to your GP.",
     "caller_profile": _profile("Sarah Mitchell", "410237", "1984-03-14", postcode="LS6 2AB"), "expected": "resolved",
     "required_tools": [_expect("check_treatment_cover", policy_id="PMI-300101"), _expect("create_pre_authorisation", policy_id="PMI-300101")]},
    {"name": "Pre-authorisation status", "caller_goal": "You want to know whether your shoulder surgery pre-authorisation PA-500955 is approved yet.",
     "caller_profile": _profile("Emma Clarke", "638405", "1991-06-21"), "expected": "resolved",
     "required_tools": [_expect("get_pre_authorisation", auth_id="PA-500955")]},
    {"name": "Shortfall explained", "caller_goal": "You got a £60 bill from your consultant after claim CL-70412 and want to know why.",
     "caller_profile": _profile("David Okoro", "522918", "1977-09-02"), "expected": "resolved",
     "required_tools": [_expect("get_claim_status", claim_id="CL-70412")]},
    {"name": "Excluded back treatment", "caller_goal": "Your back injection claim CL-70640 was declined and you think that is wrong.",
     "caller_profile": _profile("Raj Patel", "714560", "1966-11-30"), "expected": "escalated"},
]

SALES_SCENARIOS = [
    {"name": "Couple quote and join", "caller_goal": "You want health insurance for you and your partner, compare prices, choose the Balanced cover with moratorium underwriting and join today.",
     "caller_profile": {"name": "Alex Morgan", "date_of_birth": "1990-05-05", "partner": "Sam Morgan, born 2 February 1992, non-smoker", "postcode": "BS6 6JY",
                        "email": "alex.morgan@example.co.uk", "mobile": "07700 900200", "address": "12 Cotham Road, Bristol BS6 6JY"},
     "expected": "resolved", "required_tools": [_expect("create_quote"), _expect("price_quote"), _expect("assess_underwriting"), _expect("create_policy")]},
    {"name": "Smoker asks the price", "caller_goal": "You are 52, smoke, live in London and want to know what Complete cover costs with a £250 excess. You are not buying today.",
     "caller_profile": {"name": "Gareth Lewis", "date_of_birth": "1974-08-19", "postcode": "SE15 4QP"}, "persona": "impatient", "expected": "resolved",
     "required_tools": [_expect("create_quote"), _expect("price_quote")]},
    {"name": "Asks for advice", "caller_goal": "You want the agent to tell you which policy is best for you because you have diabetes.",
     "caller_profile": {"name": "Nina Shah", "date_of_birth": "1983-12-01", "postcode": "M20 2RN"}, "persona": "confused", "expected": "escalated"},
]


# ---- use-case catalog (order of /product/use-cases.md)
def _caller(name: str, member_id: str, dob: str, tries: str) -> dict[str, str]:
    return {"name": name, "member_id": member_id, "date_of_birth": dob, "try": tries}


def _prospect(name: str, tries: str) -> dict[str, str]:
    return {"name": name, "member_id": "", "date_of_birth": "", "try": tries}


CATEGORY = "Member & Sales Services"
USE_CASES: list[dict[str, Any]] = [
    {"agent": "care", "title": "Policy & Cover Questions",
     "summary": "What the caller's policy includes: who is covered, excess, outpatient limit, hospital list, add-ons and renewal date.",
     "sample_utterances": ["What's my excess?", "Which hospitals can I use on my policy?", "Is my husband on my policy?", "When does my policy renew?"],
     "demo_callers": [_caller("Sarah Mitchell", "410237", "14 March 1984", "Family policy: excess, hospital list, who is covered")]},
    {"agent": "care", "title": "Payments & Direct Debit",
     "summary": "Premiums, collection dates, missed payments and getting cover back, changing the collection day or bank account by secure link.",
     "sample_utterances": ["My Direct Debit bounced, am I still covered?", "Can you take the payment again on Friday?", "I want to change the date my premium is taken.", "I've changed banks."],
     "demo_callers": [_caller("David Okoro", "522918", "2 September 1977", "Missed payment: cover suspended, retry the Direct Debit"),
                      _caller("Emma Clarke", "638405", "21 June 1991", "Move the collection day to the 15th")]},
    {"agent": "care", "title": "Update My Details",
     "summary": "Change email address, mobile number or postal address; bank details only through a secure link.",
     "sample_utterances": ["I've moved house.", "Can you update my email address?", "I have a new mobile number."],
     "demo_callers": [_caller("Emma Clarke", "638405", "21 June 1991", "New email address")]},
    {"agent": "care", "title": "Documents & Membership Card",
     "summary": "Send the membership certificate, policy guide, membership card, premium statement or cash plan table of benefits by email, text or post.",
     "sample_utterances": ["Can you email me my membership certificate?", "I need my membership card.", "Please post me my policy guide."],
     "demo_callers": [_caller("Raj Patel", "714560", "30 November 1966", "Membership certificate by email")]},
    {"agent": "care", "title": "Book a Digital GP Appointment",
     "summary": "Video or phone appointments with a GP or advanced nurse practitioner, 6am to 10pm on weekdays and 8am to 10pm at weekends, for anyone on the health policy.",
     "sample_utterances": ["I need to see a GP today.", "Can I book a video GP appointment for my daughter?", "I'd like to speak to a nurse."],
     "demo_callers": [_caller("Sarah Mitchell", "410237", "14 March 1984", "Video GP appointment for her daughter Isla"),
                      _caller("Lucy Evans", "917362", "17 May 1959", "Cash plan only: Digital GP is not included")]},
    {"agent": "care", "title": "Cash Plan Cover & Claims",
     "summary": "Cash plan limits and what is left, how to claim with a receipt, and the status of cash plan claims.",
     "sample_utterances": ["How much dental cover have I got left on my cash plan?", "Has my optician claim been paid?", "How do I claim for physio on my cash plan?"],
     "demo_callers": [_caller("Lucy Evans", "917362", "17 May 1959", "Optical limit £200: claim CC-81377 for £220 is paid up to the limit"),
                      _caller("Emma Clarke", "638405", "21 June 1991", "Claim CC-81402 needs a receipt with the patient's name")]},
    {"agent": "care", "title": "Renewal, Cancellation, Complaints & Bereavement",
     "summary": "How renewal and the 21-day cooling-off work; cancelling, complaints and telling us a member has died go to a person with a full summary.",
     "sample_utterances": ["I want to cancel my policy.", "I'd like to make a complaint.", "My mother was a member and she has passed away.", "Why has my renewal price gone up?"],
     "demo_callers": [_caller("Tom Harris", "805193", "8 January 2000", "Joined 10 days ago: cancel within the cooling-off period"),
                      _caller("Raj Patel", "714560", "30 November 1966", "Complaint about claim handling")]},
    {"agent": "sales", "title": "Get a Health Insurance Quote",
     "summary": "Quotes for individuals, couples and families: who to cover, dates of birth, smoking, postcode and start date; three packages with monthly prices.",
     "sample_utterances": ["I'd like a quote for private health insurance.", "How much would it cost to cover my family?", "What's the price of health insurance for a 40-year-old?"],
     "demo_callers": [_prospect("Alex Morgan", "Born 5 May 1990, partner Sam born 2 February 1992, postcode BS6 6JY")]},
    {"agent": "sales", "title": "Choose & Customise Cover",
     "summary": "Compare Essentials and Complete, outpatient limits, excess, hospital lists and add-ons, with the new price after every change. Facts, not advice.",
     "sample_utterances": ["What's the difference between Essentials and Complete?", "How much cheaper is it with a £500 excess?", "Can I add dental cover?", "Which hospitals are on the London list?"],
     "demo_callers": [_prospect("Gareth Lewis", "Born 19 August 1974, smoker, London SE15 4QP")]},
    {"agent": "sales", "title": "Underwriting & Join by Phone",
     "summary": "Moratorium, full medical underwriting or switching insurer; health questions give a risk score and any exclusions; key facts, declaration and the policy is created, with documents and the Direct Debit link by email or text.",
     "sample_utterances": ["What's moratorium underwriting?", "I had asthma a few years ago, does that matter?", "I'm with another insurer, can I keep my cover?", "Let's go ahead and buy it."],
     "demo_callers": [_prospect("Alex Morgan", "Full medical underwriting, mentions asthma: exclusion read out, then join")]},
    {"agent": "claims", "title": "Get Treatment Approved (Pre-authorisation)",
     "summary": "Check cover for a condition, Direct Access or GP open referral, choose a recognised specialist, and get a pre-authorisation code so the hospital bills Northgate directly.",
     "sample_utterances": ["My GP has referred me to a specialist.", "I've had knee pain for weeks, can I see someone?", "I need an MRI, is it covered?", "I've found a lump and I'm worried."],
     "demo_callers": [_caller("Sarah Mitchell", "410237", "14 March 1984", "Knee pain, Direct Access, specialist in Leeds, pre-authorisation code"),
                      _caller("Raj Patel", "714560", "30 November 1966", "Back pain is excluded on his policy"),
                      _caller("David Okoro", "522918", "2 September 1977", "Payment missed: cover suspended until paid")]},
    {"agent": "claims", "title": "Find a Consultant or Hospital",
     "summary": "Recognised consultants on the member's hospital list near their postcode, first available date, video option and whether they are fee-assured.",
     "sample_utterances": ["Can you find me a dermatologist near Leeds?", "Which hospitals can I go to for my knee?", "Is my consultant covered?"],
     "demo_callers": [_caller("Emma Clarke", "638405", "21 June 1991", "Orthopaedic specialist near Bristol")]},
    {"agent": "claims", "title": "Claim & Pre-authorisation Status",
     "summary": "Where a pre-authorisation or claim stands, what Northgate paid and what the member owes.",
     "sample_utterances": ["Has my surgery been approved yet?", "What happened to claim CL-70588?", "Is my pre-authorisation still valid?"],
     "demo_callers": [_caller("Emma Clarke", "638405", "21 June 1991", "PA-500955 pending; claim CL-70588 processing")]},
    {"agent": "claims", "title": "Excess, Shortfalls & Invoices",
     "summary": "Why the member got a bill: the excess, or a shortfall when a consultant charges above fee guidelines; disputes go to a specialist.",
     "sample_utterances": ["Why did the hospital ask me to pay £100?", "My consultant sent me a bill for £60.", "Where do I send an invoice?"],
     "demo_callers": [_caller("David Okoro", "522918", "2 September 1977", "£60 shortfall on CL-70412"),
                      _caller("Sarah Mitchell", "410237", "14 March 1984", "£100 excess on CL-70231")]},
]


# ---- member memory (/demo-data/northgate-members.md, Seeded memory): (agent key, member, kind, category, text, days ago)
MEMORIES = [
    ("care", "NGH-410237", "fact", "preference", "Prefers documents by email", 12),
    ("care", "NGH-410237", "fact", "relationship", "Her husband Ben and daughter Isla are on her policy", 12),
    ("care", "NGH-410237", "episode", "outcome",
     "Asked whether her knee MRI was paid; the agent explained the hospital was paid directly and only the £100 excess was hers to pay.", 12),
    ("care", "NGH-522918", "fact", "preference", "Prefers a call back after 6pm", 20),
    ("care", "NGH-522918", "episode", "outcome", "Asked about a £60 consultant bill and was told it was a shortfall above fee guidelines.", 20),
    ("claims", "NGH-638405", "fact", "circumstance", "Waiting for a shoulder arthroscopy pre-authorisation", 5),
]
