"""Seed definitions: tenants, personas, tools, skills, agents, use cases, regression scenarios.

Spec: /demo-data/evergreen-health.md, /product/use-cases.md
"""
from __future__ import annotations

from typing import Any

CARE_TENANT = "evergreen-care"
SANDBOX_TENANT = "evergreen-sandbox"

TENANTS = [
    {"id": CARE_TENANT, "name": "Evergreen Health · Customer Support & Channels", "industry": "Health insurance"},
    {"id": SANDBOX_TENANT, "name": "Evergreen Health · New Business Unit (sandbox)", "industry": "Health insurance"},
]

_EMPTY: dict[str, Any] = {"type": "object", "properties": {}}
DISCLOSURE = "I'm a virtual assistant, and this call may be recorded for quality."


def _params(required: list[str] | None = None, **props: str) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()}, "required": required or []}


# ---- tools (16): verify = requires_verification
def _tool(name: str, description: str, method: str, url: str, parameters: dict[str, Any] | None = None, verify: bool = False) -> dict[str, Any]:
    return {"name": name, "description": description, "method": method, "url": url, "parameters": parameters or _EMPTY, "requires_verification": verify}


TOOLS: list[dict[str, Any]] = [
    {"name": "verify_member", "description": "Verify the person's identity with member ID and date of birth. Required before any member-specific information.",
     "method": "POST", "url": "/mock/healthcare/verify",
     "parameters": _params(["member_id", "date_of_birth"], member_id="Member ID as spoken, e.g. 482913 or EVG-482913", date_of_birth="Date of birth in YYYY-MM-DD format"),
     "requires_verification": False, "is_verification": True},
    _tool("get_member_policies", "List the verified member's policies: policy number, type (health or motor), product, status, start and renewal date.",
          "GET", "/mock/insurance/policies", verify=True),
    _tool("get_policy_details", "Details of one policy of the verified member: status, cover period, premium, payment status, next payment and renewal date, grace period.",
          "GET", "/mock/insurance/policies/{policy_id}", _params(["policy_id"], policy_id="Policy number like HP-100231 or MP-200415"), verify=True),
    _tool("get_member_claims", "List the verified member's recent claims (claim number, type, service, date, status).", "GET", "/mock/healthcare/claims", verify=True),
    _tool("get_claim_status", "Status of one claim of the verified member by claim number (e.g. C-20931): amounts, timeline, denial reason and next step.",
          "GET", "/mock/healthcare/claims/{claim_id}", _params(["claim_id"], claim_id="Claim number like C-20931"), verify=True),
    _tool("get_benefits", "Plan benefits for the verified member: deductible and out-of-pocket amounts met and remaining, and copays by visit type.",
          "GET", "/mock/healthcare/benefits", verify=True),
    _tool("get_coverage_detail", "Coverage of one benefit on a health policy: covered, annual limit, used, remaining, waiting period, pre-authorization, co-pay.",
          "GET", "/mock/insurance/policies/{policy_id}/coverage",
          _params(["policy_id", "benefit"], policy_id="Health policy number like HP-100231",
                  benefit="dental, optical, outpatient, inpatient, maternity, mental_health or physiotherapy"), verify=True),
    _tool("find_providers", "Find in-network providers by specialty, optionally near a zip code.", "GET", "/mock/healthcare/providers",
          _params(["specialty"], specialty="e.g. dermatology, primary care, pediatrics, dentistry", zip="5-digit zip code")),
    _tool("list_documents", "List the documents the document center can send for a policy, with delivery options.", "GET", "/mock/insurance/documents",
          _params(["policy_id"], policy_id="Policy number like HP-100231 or MP-200415"), verify=True),
    _tool("request_document", "Send a policy document by email, download link or post. A Green Card (motor policies only) also needs countries, travel_start and travel_end (YYYY-MM-DD).",
          "POST", "/mock/insurance/documents/request",
          {"type": "object", "properties": {
              "policy_id": {"type": "string", "description": "Policy number like MP-200415"},
              "document_type": {"type": "string", "description": "policy_schedule, policy_wording, membership_card, certificate_of_insurance, premium_invoice, tax_certificate or green_card"},
              "delivery": {"type": "string", "description": "email, download or post (a Green Card: email or download)"},
              "countries": {"type": "array", "items": {"type": "string"}, "description": "Green Card: destination countries"},
              "travel_start": {"type": "string", "description": "Green Card: first day of travel, YYYY-MM-DD"},
              "travel_end": {"type": "string", "description": "Green Card: last day of travel, YYYY-MM-DD"},
          }, "required": ["policy_id", "document_type", "delivery"]}, verify=True),
    _tool("get_renewal_quote", "Renewal quote for a policy within 90 days of renewal: new premium, change percent, reasons and options.",
          "GET", "/mock/insurance/policies/{policy_id}/renewal-quote", _params(["policy_id"], policy_id="Policy number from the call context"), verify=True),
    _tool("record_renewal_decision", "Record the policyholder's renewal decision: accept, decline or callback (callback needs a time).",
          "POST", "/mock/insurance/policies/{policy_id}/renewal-decision",
          _params(["policy_id", "decision"], policy_id="Policy number from the call context", decision="accept, decline or callback",
                  option="The renewal option chosen, if any", callback_time="When to call back, for example tomorrow morning", note="One short note"), verify=True),
    _tool("get_onboarding_status", "The verified member's onboarding checklist: each step and whether it is done.", "GET", "/mock/insurance/onboarding", verify=True),
    _tool("complete_onboarding_step", "Mark an onboarding step done. For communication_preferences pass value email, sms or post.",
          "POST", "/mock/insurance/onboarding/steps/{step_id}",
          _params(["step_id"], step_id="confirm_contact_details, communication_preferences, register_online_account, download_membership_card, choose_primary_provider or review_waiting_periods",
                  value="Only for communication_preferences: email, sms or post"), verify=True),
    _tool("get_authorization_limit", "Claim authorization limits by staff role (claims_handler, senior_handler, team_leader, claims_manager) and claim type (inpatient, outpatient, dental).",
          "GET", "/mock/internal/authorization-limits",
          _params(["role"], role="claims_handler, senior_handler, team_leader or claims_manager", claim_type="inpatient, outpatient or dental")),
    _tool("get_escalation_contact", "Who to contact internally for a topic: fraud, complaints, legal, data_protection, it_service_desk or medical_director.",
          "GET", "/mock/internal/contacts", _params(["topic"], topic="fraud, complaints, legal, data_protection, it_service_desk or medical_director")),
]

# ---- skills
_VERIFY_INBOUND = {
    "name": "Identity verification",
    "description": "Any request about a specific policy, claim, document or benefit.",
    "instructions": (
        "1. Ask for the caller's member ID and date of birth.\n"
        "2. Call verify_member with the member ID and the date of birth in YYYY-MM-DD format.\n"
        "3. If verified, thank them by first name and continue with their request. If not, ask them to repeat both once.\n"
        "4. Never read back the full member ID or date of birth."),
    "required_tools": ["verify_member"], "escalate_when": "Verification fails twice.",
}
_VERIFY_OUTBOUND = {
    "name": "Identity verification (outbound call)",
    "description": "Right after the callee confirms who they are, before any detail is shared.",
    "instructions": (
        "1. Confirm you are speaking with the person named in the call context; if someone else answered, do not say why you are calling.\n"
        "2. Say this is an Evergreen Health call and ask for their date of birth.\n"
        "3. Call verify_member with the member_id from the call context and the date of birth in YYYY-MM-DD format.\n"
        "4. If verified, continue. If not, ask once more; if it fails again apologize, say you will try later and end the call.\n"
        "5. Never read the member ID aloud."),
    "required_tools": ["verify_member"], "escalate_when": "Verification fails twice.",
}

CARE_SKILLS: list[dict[str, Any]] = [
    _VERIFY_INBOUND,
    {"name": "Policy inquiry & status", "description": "Which policies the caller holds, whether they are active, premiums, payments and renewal dates.",
     "instructions": (
         "1. Verify identity first.\n"
         "2. Call get_member_policies. If there are several policies, name them briefly and ask which one they mean.\n"
         "3. Call get_policy_details for that policy.\n"
         "4. Give the status, the premium, whether payments are up to date, the next payment date and the renewal date.\n"
         "5. If a payment is overdue, explain the grace period (search_knowledge) and how to pay."),
     "required_tools": ["verify_member", "get_member_policies", "get_policy_details"],
     "escalate_when": "The caller wants to cancel, change cover mid-term or dispute a charge."},
    {"name": "Claims status tracking", "description": "Caller asks whether a claim was paid, denied or is still processing, or what happens next.",
     "instructions": (
         "1. Verify identity first.\n"
         "2. Ask for the claim number. If they don't have it, call get_member_claims and confirm the claim by service and date.\n"
         "3. Call get_claim_status.\n"
         "4. In one or two sentences give the status, what the plan paid and what the member owes - or the expected decision date or the denial reason - and the next step.\n"
         "5. If the claim is denied, explain the reason and that appeals are handled by a specialist."),
     "required_tools": ["verify_member", "get_member_claims", "get_claim_status"],
     "escalate_when": "The caller disputes a denial or wants to file an appeal."},
    {"name": "Document center & Green Card", "description": "Policy documents (schedule, wording, membership card, invoice, certificates) and the Green Card for driving abroad.",
     "instructions": (
         "1. Verify identity first, then identify the policy with get_member_policies.\n"
         "2. Call list_documents for that policy and confirm which document and how to deliver it: email, download link or post.\n"
         "3. A Green Card is the international motor insurance certificate: it needs an active motor policy. Ask for every destination country and the travel start and end dates (up to 90 days), then confirm them back.\n"
         "4. Call request_document and tell the caller the delivery time. For email, say it is sent to the address on file without reading it out.\n"
         "5. If the policy is not a motor policy, explain that and do not request one."),
     "required_tools": ["verify_member", "get_member_policies", "list_documents", "request_document"],
     "escalate_when": "A destination is not covered, the policy is not active, or the caller needs a document the document center does not offer."},
    {"name": "Coverage information", "description": "What the plan covers: benefits, limits and what is left, waiting periods, deductible, copays and pre-authorization.",
     "instructions": (
         "1. For general questions on how cover, waiting periods, exclusions or pre-authorization work, call search_knowledge.\n"
         "2. For the caller's own limits: verify identity, find the health policy with get_member_policies, then call get_coverage_detail with the benefit.\n"
         "3. For deductible, out-of-pocket or copays call get_benefits.\n"
         "4. Answer with the specific numbers: limit, used, remaining, waiting period, whether pre-authorization is needed.\n"
         "5. Never give medical advice or say whether a specific treatment is medically appropriate."),
     "required_tools": ["verify_member", "get_member_policies", "get_coverage_detail", "get_benefits"],
     "escalate_when": "Coverage for a specific treatment is ambiguous or needs a clinical decision."},
    {"name": "Find a provider", "description": "Caller needs an in-network doctor, dentist or facility.",
     "instructions": (
         "1. Ask what kind of doctor they need and their zip code.\n"
         "2. Call find_providers.\n"
         "3. Offer up to two options with name, practice and whether they accept new patients; give the phone number if asked.\n"
         "4. Remind HMO members that specialists need a referral from their primary care doctor."),
     "required_tools": ["find_providers"], "escalate_when": "No in-network provider is found for the needed specialty."},
    {"name": "Appeals and grievances", "description": "Caller wants to appeal a denial or file a complaint.",
     "instructions": (
         "1. Acknowledge the caller's frustration briefly.\n"
         "2. Verify identity and identify the claim (get_member_claims or get_claim_status) so the specialist has the details.\n"
         "3. Explain the denial reason in one sentence.\n"
         "4. Call escalate_to_human with reason_category policy_required."),
     "required_tools": ["verify_member", "get_member_claims", "get_claim_status"], "escalate_when": "Always, once the claim is identified."},
]

RENEWAL_SKILLS: list[dict[str, Any]] = [
    _VERIFY_OUTBOUND,
    {"name": "Renewal conversation", "description": "After verification: explain the renewal price, the reasons and the options, and record the decision.",
     "instructions": (
         "1. Call get_renewal_quote with the policy_id from the call context.\n"
         "2. In two sentences give the renewal date, the new yearly premium and the change in percent.\n"
         "3. Give the main reason or reasons from the quote in plain words.\n"
         "4. Offer the options from the quote (a higher excess or paying annually can lower the price) and ask what they would like to do.\n"
         "5. Call record_renewal_decision with accept, decline or callback and the chosen option; then say what happens next.\n"
         "6. For questions about how renewals, price changes or discounts work, call search_knowledge."),
     "required_tools": ["verify_member", "get_renewal_quote", "record_renewal_decision"],
     "escalate_when": "The callee is upset, wants to cancel because of a complaint, or asks for advice you cannot give."},
    {"name": "Callback scheduling", "description": "The callee says it is a bad time or wants to think it over.",
     "instructions": (
         "1. Offer to call back and ask for a convenient time.\n"
         "2. If the date of birth has not been verified yet, ask for it now (this shares nothing) and call verify_member.\n"
         "3. Call record_renewal_decision with decision callback and the callback_time they gave.\n"
         "4. Confirm the time back and end the call politely."),
     "required_tools": ["verify_member", "record_renewal_decision"], "escalate_when": ""},
]

ONBOARDING_SKILLS: list[dict[str, Any]] = [
    _VERIFY_OUTBOUND,
    {"name": "Welcome checklist", "description": "After verification: walk the new policyholder through their pending onboarding steps.",
     "instructions": (
         "1. Welcome them to Evergreen Health and call get_onboarding_status.\n"
         "2. Take the pending steps one at a time, in order, explaining each in a sentence.\n"
         "3. As soon as a step is done call complete_onboarding_step (for communication_preferences pass value email, sms or post).\n"
         "4. For waiting periods and the first 30 days, call search_knowledge.\n"
         "5. Finish by saying how many steps are left, if any."),
     "required_tools": ["verify_member", "get_onboarding_status", "complete_onboarding_step"],
     "escalate_when": "The member reports an error in their policy or cannot be verified."},
    {"name": "Digital account and card", "description": "Online account registration and the membership card.",
     "instructions": (
         "1. Explain that registering takes about five minutes at the Evergreen Health member portal or in the app; use search_knowledge for the steps.\n"
         "2. Offer to email the membership card: call request_document with the policy_id from the call context, document_type membership_card and delivery email.\n"
         "3. Then mark download_membership_card or register_online_account done only if the member confirms they did it."),
     "required_tools": ["request_document", "complete_onboarding_step"], "escalate_when": ""},
]

INTERNAL_SKILLS: list[dict[str, Any]] = [
    {"name": "Procedure lookup", "description": "Questions about claims handling, complaints, fraud indicators, data protection and call-handling standards.",
     "instructions": (
         "1. Call search_knowledge with the question.\n"
         "2. Answer in a few short sentences and name the source article.\n"
         "3. If nothing relevant is found, say the procedure is not documented and offer the escalation contact."),
     "required_tools": ["search_knowledge"], "escalate_when": "The question is not covered by internal knowledge twice."},
    {"name": "Authorization limits", "description": "What a staff role may approve for a claim type.",
     "instructions": (
         "1. Ask for the role and the claim type if either is missing.\n"
         "2. Call get_authorization_limit with role and claim_type and quote the amount.\n"
         "3. Mention that amounts above the limit need the next role to approve (search_knowledge: authorization limits policy)."),
     "required_tools": ["get_authorization_limit"], "escalate_when": ""},
    {"name": "Escalation contacts", "description": "Who to contact for fraud, complaints, legal, data protection, IT or clinical questions.",
     "instructions": "1. Work out the topic.\n2. Call get_escalation_contact and give the team, extension and hours.",
     "required_tools": ["get_escalation_contact"], "escalate_when": ""},
]

# ---- persona library: (name, description, voice, speed, greeting, disclosure, opening, style)
PERSONAS: list[dict[str, Any]] = [
    {"name": "Ava", "description": "Warm, calm and concise; the default for customer calls.", "voice": "aura-2-thalia-en", "speed": 1.0,
     "greeting": "Thanks for calling Evergreen Health member services, this is Ava.", "disclosure": f"{DISCLOSURE} How can I help you today?", "opening": "",
     "style": "Warm, calm and concise. One question at a time. Plain language, no insurance jargon unless the caller uses it."},
    {"name": "Grace", "description": "Formal and reassuring; suits appeals and sensitive conversations.", "voice": "aura-2-helena-en", "speed": 0.95,
     "greeting": "Good day, you have reached Evergreen Health member services. My name is Grace.", "disclosure": f"{DISCLOSURE} How may I assist you?", "opening": "",
     "style": "Formal, measured and reassuring. Full sentences, no slang, acknowledge feelings before facts."},
    {"name": "Leo", "description": "Upbeat and efficient; suits outbound renewal calls and quick lookups.", "voice": "aura-2-apollo-en", "speed": 1.05,
     "greeting": "Evergreen Health member services, this is Leo.", "disclosure": f"{DISCLOSURE} What can I do for you?",
     "opening": "Hello, may I speak with {first_name}? This is Leo calling from Evergreen Health about {purpose}.",
     "style": "Upbeat and efficient. Short sentences, get to the point quickly, friendly but not chatty."},
    {"name": "Maya", "description": "Friendly and encouraging; suits welcome and onboarding calls.", "voice": "aura-2-andromeda-en", "speed": 1.0,
     "greeting": "Evergreen Health member services, this is Maya.", "disclosure": f"{DISCLOSURE} How can I help?",
     "opening": "Hi {first_name}, this is Maya from Evergreen Health. I'm calling to welcome you and help you get set up.",
     "style": "Friendly and encouraging. Celebrate small steps, keep explanations short, check the person is comfortable before moving on."},
    {"name": "Sage", "description": "Neutral and precise; short answers for staff.", "voice": "aura-2-orion-en", "speed": 1.0,
     "greeting": "Evergreen internal knowledge assistant.", "disclosure": "I'm a virtual assistant. What do you need to know?", "opening": "",
     "style": "Neutral and precise. Short answers: the step, the limit or the contact, then stop."},
]

# ---- agents
_STD_NEVER = ["Promise that a claim, appeal or authorization will be approved.", "Share information about anyone other than the verified member."]

AGENTS: list[dict[str, Any]] = [
    {
        "key": "care", "name": "Customer Care Agent", "mode": "inbound", "persona": "Ava", "kb": "customer-care",
        "description": "Policy inquiries, claims status, documents and Green Card, and coverage questions for Evergreen Health members.",
        "turn_detection": {"mode": "semantic", "min_silence_ms": 700, "max_extra_wait_ms": 1500, "evaluator": "heuristic", "allow_interruptions": True},
        "tools": ["verify_member", "get_member_policies", "get_policy_details", "get_member_claims", "get_claim_status", "get_benefits",
                  "get_coverage_detail", "find_providers", "list_documents", "request_document"],
        "skills": CARE_SKILLS,
        "policy": {
            "rules": [
                "Verify identity with member ID and date of birth before sharing any policy, claim, document or benefit information.",
                "When explaining a claim, give its status, what the plan paid, what the member owes and the next step.",
                "For a Green Card, collect every destination country and the travel start and end dates before requesting it.",
                "Offer the 24/7 nurse line for health questions.",
            ],
            "escalate_when": [
                "The caller wants to file an appeal or grievance, or disputes a denial.",
                "The caller wants to cancel a policy, change cover mid-term or dispute a charge.",
                "A document or Green Card destination is not available through the document center.",
                "The caller reports a provider billing error that needs investigation.",
            ],
            "never": _STD_NEVER, "max_turns": 16,
            "handoff_message": "I'm connecting you with a specialist who will have all the details, so you won't need to repeat yourself.",
        },
    },
    {
        "key": "renewals", "name": "Renewal Outreach Agent", "mode": "outbound", "persona": "Leo", "kb": "renewals",
        "targets_url": "/mock/insurance/outreach/renewals",
        "description": "Calls policyholders ahead of renewal: explains the new price, offers options and records the decision.",
        "turn_detection": {"mode": "semantic", "min_silence_ms": 700, "max_extra_wait_ms": 1500, "evaluator": "heuristic", "allow_interruptions": True},
        "tools": ["verify_member", "get_renewal_quote", "record_renewal_decision"],
        "skills": RENEWAL_SKILLS,
        "policy": {
            "rules": [
                "Do not share any price, policy or claim detail until the callee has verified their date of birth.",
                "State the premium change, the main reasons and the options in plain language, then ask for a decision.",
                "Respect a refusal or a request to stop calling.",
            ],
            "escalate_when": ["The callee is upset or wants to make a complaint.", "The callee wants to cancel because of a complaint, or asks for advice you cannot give."],
            "never": ["Pressure the callee or imply that cover will lapse unless they decide now.", "Compare with other insurers or give financial advice."],
            "max_turns": 16, "handoff_message": "I'll have a renewals specialist call you back shortly.",
        },
    },
    {
        "key": "onboarding", "name": "Welcome & Onboarding Agent", "mode": "outbound", "persona": "Maya", "kb": "onboarding",
        "targets_url": "/mock/insurance/outreach/onboarding",
        "description": "Welcome calls to new policyholders: completes the onboarding checklist and sends the membership card.",
        "turn_detection": {"mode": "semantic", "min_silence_ms": 700, "max_extra_wait_ms": 1500, "evaluator": "heuristic", "allow_interruptions": True},
        "tools": ["verify_member", "get_onboarding_status", "complete_onboarding_step", "request_document"],
        "skills": ONBOARDING_SKILLS,
        "policy": {
            "rules": [
                "Do not share any policy detail until the callee has verified their date of birth.",
                "Record each step with complete_onboarding_step as soon as the callee completes it.",
                "Finish by summarizing what is left.",
            ],
            "escalate_when": ["The member reports an error in their policy or cannot be verified."],
            "never": ["Ask for passwords, card numbers or bank details."],
            "max_turns": 16, "handoff_message": "I'll arrange for a member services colleague to follow up with you.",
        },
    },
    {
        "key": "internal", "name": "Internal Knowledge Assistant", "mode": "internal", "persona": "Sage", "kb": "internal",
        "description": "Answers Evergreen staff questions on procedures, authorization limits and who to contact.",
        "turn_detection": {"mode": "vad", "min_silence_ms": 700, "max_extra_wait_ms": 1500, "evaluator": "heuristic", "allow_interruptions": True},
        "tools": ["get_authorization_limit", "get_escalation_contact"],
        "skills": INTERNAL_SKILLS,
        "policy": {
            "rules": ["Search internal knowledge before answering and name the source article.", "Say plainly when a procedure is not documented."],
            "escalate_when": ["The question is not covered by internal knowledge."],
            "never": ["Disclose individual member or claim data.", "Guess a procedure, limit or deadline."],
            "max_turns": 16, "handoff_message": "I can't answer that reliably, so I'll flag it to the knowledge team.",
        },
    },
]

SANDBOX_KB = "sandbox"


# ---- regression scenarios (Customer Care Agent)
def _profile(name: str, member_id: str, dob: str, **extra: str) -> dict[str, str]:
    return {"name": name, "member_id": member_id, "date_of_birth": dob, **extra}


SCENARIOS = [
    {"name": "Policy status", "caller_goal": "You want to know if your health policy is active and when it renews.",
     "caller_profile": _profile("Maria Lopez", "482913", "1986-04-12"), "expected": "resolved"},
    {"name": "Claim paid", "caller_goal": "You want to know whether claim C-20931 was paid and how much you owe.",
     "caller_profile": _profile("Maria Lopez", "482913", "1986-04-12", claim_number="C-20931"), "expected": "resolved"},
    {"name": "Green Card for Spain", "caller_goal": "You are driving to Spain next month and need a Green Card for your car policy, emailed to you.",
     "caller_profile": _profile("James Carter", "337120", "1979-11-02", destination="Spain", travel="leaving in three weeks, for ten days", delivery="email"), "expected": "resolved"},
    {"name": "Dental coverage", "caller_goal": "You want to know how much of your dental allowance is left and whether there is a waiting period.",
     "caller_profile": _profile("Priya Nair", "559804", "1992-07-23"), "expected": "resolved"},
    {"name": "Policy schedule by email", "caller_goal": "You want your policy schedule emailed to you.",
     "caller_profile": _profile("Daniel Kim", "801456", "2001-03-08"), "expected": "resolved"},
    {"name": "Appeal denied claim", "caller_goal": "Your surgery claim C-31544 was denied and you want to appeal it.",
     "caller_profile": _profile("James Carter", "337120", "1979-11-02", claim_number="C-31544"), "expected": "escalated"},
]


# ---- use-case catalog (order of /product/use-cases.md)
def _caller(name: str, member_id: str, dob: str, tries: str) -> dict[str, str]:
    return {"name": name, "member_id": member_id, "date_of_birth": dob, "try": tries}


CATEGORY = "Customer Support & Channels"
USE_CASES: list[dict[str, Any]] = [
    {"agent": "care", "title": "Policy Inquiry & Status",
     "summary": "Which policies the caller holds, whether they are active, what they pay, payment status and renewal date.",
     "sample_utterances": ["Is my health policy still active, and when does it renew?", "What policies do I have with you?", "When is my next payment due?", "My account says a payment is overdue, what happens now?"],
     "demo_callers": [_caller("Maria Lopez", "482913", "April 12, 1986", "Health policy, renews in 25 days"),
                      _caller("Robert Chen", "610277", "January 30, 1958", "Payment overdue, inside the grace period")]},
    {"agent": "care", "title": "Claims Status Tracking",
     "summary": "Status, amounts, expected decision date and timeline of a claim; denied claims go to a specialist with a full packet.",
     "sample_utterances": ["What happened with claim C-20931?", "Has my lab work claim been processed yet?", "Why was my surgery claim denied, and can I appeal?"],
     "demo_callers": [_caller("Maria Lopez", "482913", "April 12, 1986", "Claim C-20931 (paid) and C-20977 (processing)"),
                      _caller("James Carter", "337120", "November 2, 1979", "Claim C-31544 (denied): ask to appeal and watch the escalation")]},
    {"agent": "care", "title": "Document Center & Green Card",
     "summary": "Send policy documents by email, download or post, and issue the Green Card, the international motor insurance certificate for driving abroad.",
     "sample_utterances": ["I'm driving to Spain next month. Can you email me a Green Card?", "Please email me my policy schedule.", "I need my membership card sent to me."],
     "demo_callers": [_caller("James Carter", "337120", "November 2, 1979", "Green Card for Spain by email; try 'the USA' to see it refused"),
                      _caller("Maria Lopez", "482913", "April 12, 1986", "Ask for a Green Card: she has no motor policy"),
                      _caller("Daniel Kim", "801456", "March 8, 2001", "Policy schedule by email")]},
    {"agent": "renewals", "title": "Outbound Renewal Calls",
     "summary": "The agent phones the policyholder before renewal, explains the price change and options, and records accept, decline or callback.",
     "sample_utterances": ["Yes, speaking.", "Why has the price gone up?", "Is there a cheaper option?", "Now isn't a good time, can you call me tomorrow?"],
     "demo_callers": [_caller("James Carter", "337120", "November 2, 1979", "Motor policy, +8%, renews in 13 days"),
                      _caller("Maria Lopez", "482913", "April 12, 1986", "Health policy, +4%, renews in 25 days")]},
    {"agent": "onboarding", "title": "Policyholder Onboarding",
     "summary": "A welcome call to new policyholders: confirm contact details, preferences, online account, membership card and waiting periods.",
     "sample_utterances": ["Yes, this is Aisha.", "I haven't registered online yet.", "Please email me my membership card.", "How long is the waiting period for dental?"],
     "demo_callers": [_caller("Aisha Okafor", "725031", "September 15, 1990", "Five steps left"),
                      _caller("Daniel Kim", "801456", "March 8, 2001", "Three steps left")]},
    {"agent": "internal", "title": "Internal Knowledge Assistant",
     "summary": "Staff ask about claims handling, authorization limits, complaints, fraud indicators and who to contact; the assistant cites the source and never discloses member data.",
     "sample_utterances": ["What can a claims handler approve for inpatient?", "Who do I contact about a suspected fraud?", "How long do we have to respond to a complaint?", "What are the signs of claims fraud?"],
     "demo_callers": []},
    {"agent": "care", "title": "Coverage Information Support",
     "summary": "What the plan covers: benefits, limits and what is left, waiting periods, pre-authorization, copays, deductible and in-network providers.",
     "sample_utterances": ["How much of my dental allowance is left, and is there a waiting period?", "What's my specialist copay?", "Do I need pre-authorization for an MRI?", "Find me a dentist near 94110."],
     "demo_callers": [_caller("Priya Nair", "559804", "July 23, 1992", "Dental limit remaining and waiting period"),
                      _caller("Daniel Kim", "801456", "March 8, 2001", "Specialist copay and deductible")]},
]
