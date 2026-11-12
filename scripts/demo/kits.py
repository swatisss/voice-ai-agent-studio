"""Demo kit definitions for scripts/demo_kits.py: everything an agent needs, as REST API payloads.

A kit is one agent built from Markdown knowledge: persona, guardrails, knowledge files, tools, skills, use cases with
demo callers (from a use-cases.md file, the format of scripts/import_use_cases.py), and the checks the runner holds against it. All businesses and people here are fictional and synthetic.
Tool URLs may contain `{mock}`, the base URL of a mock business API that the runner serves (scripts/demo/dental_mock.py).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_DIR.parent))
from import_use_cases import load as load_use_cases  # noqa: E402 - use cases live in Markdown files


@dataclass
class Chat:
    """A scripted text call. `source` is the knowledge section (heading or title) the first search must rank first: the
    check in fake mode, where the scripted stand-in only stitches sentences together. `expect` patterns are matched against
    the reply to that turn (case-insensitive, spaces removed): the check with a real model (--live). `escalates` means the
    call must end with a hand-off, in both modes."""
    name: str
    turns: list[str]
    source: str = ""
    expect: dict[int, list[str]] = field(default_factory=dict)
    escalates: bool = False
    needs_model: bool = False  # tool conversations: the fake LLM only searches knowledge, so these run with --live only


@dataclass
class Kit:
    key: str
    agent_name: str
    description: str
    category: str
    persona: dict[str, Any]
    policy: dict[str, Any]
    knowledge: list[Path]  # uploaded as files, like the Knowledge tab's Upload button; the title comes from the frontmatter
    tools: list[dict[str, Any]]
    skills: list[dict[str, Any]]
    use_cases: list[dict[str, Any]]
    chats: list[Chat]
    mock: bool = False
    voice_pipeline: str = ""  # "realtime": OpenAI speech-to-speech, when the business unit allows it; empty keeps the agent's


# ------------------------------------------------------------------ Oakhaven Dental Care (UK dental group, mock patient system)
DENTAL_KNOWLEDGE = DEMO_DIR / "dental" / "knowledge"
VERIFY = {"type": "object", "properties": {
    "patient_id": {"type": "string", "description": "Oakhaven patient ID as spoken, e.g. OD-10231 or 10231"},
    "date_of_birth": {"type": "string", "description": "Date of birth as YYYY-MM-DD"}}, "required": ["patient_id", "date_of_birth"]}
APPOINTMENT_TYPE = {"type": "string", "enum": ["check_up", "hygiene", "new_patient_exam", "emergency", "filling", "consultation", "sedation_consultation"],
                    "description": "check_up, hygiene (scale and polish), new_patient_exam (first visit), emergency (same-day pain), "
                                   "filling, consultation (implants, aligners, whitening) or sedation_consultation"}
PRACTICE = {"type": "string", "enum": ["Leeds", "Manchester", "Bristol"], "description": "Oakhaven practice"}
TREATMENT = {"type": "string", "enum": ["check_up", "hygiene", "new_patient_exam", "emergency_appointment", "white_filling_small",
                                        "white_filling_large", "simple_extraction", "surgical_extraction", "root_canal_front",
                                        "root_canal_premolar", "root_canal_molar", "crown", "bridge", "implant", "whitening",
                                        "clear_aligners", "sedation"]}


def _tool(name: str, description: str, method: str, path: str, props: dict[str, Any], required: list[str], *,
          verified: bool = False, verification: bool = False) -> dict[str, Any]:
    return {"name": name, "description": description, "method": method, "url": "{mock}" + path,
            "parameters": {"type": "object", "properties": props, "required": required},
            "requires_verification": verified, "is_verification": verification, "timeout_s": 8}


DENTAL_TOOLS = [
    _tool("dental_verify_patient", "Verify an existing Oakhaven patient with their patient ID and date of birth. Required before any "
          "booking, appointment change, cover, estimate or claim detail.", "POST", "/dental/verify",
          VERIFY["properties"], VERIFY["required"], verification=True),
    _tool("dental_register_patient", "Register a caller who is not yet an Oakhaven patient, so they can book. Collect every field first.",
          "POST", "/dental/patients", {
              "first_name": {"type": "string"}, "last_name": {"type": "string"},
              "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
              "mobile": {"type": "string", "description": "UK mobile number for reminders"}, "preferred_practice": PRACTICE},
          ["first_name", "last_name", "date_of_birth", "mobile"], verification=True),
    _tool("dental_find_slots", "Find free appointment slots at a practice for an appointment type, from a date onward.",
          "GET", "/dental/slots", {"practice": PRACTICE, "appointment_type": APPOINTMENT_TYPE,
                                   "from_date": {"type": "string", "description": "YYYY-MM-DD, today or tomorrow; optional"}},
          ["practice", "appointment_type"]),
    _tool("dental_book_appointment", "Book a slot for the verified patient, after reading the details back and getting a yes.",
          "POST", "/dental/appointments", {"slot_id": {"type": "string", "description": "slot_id from dental_find_slots"},
                                           "appointment_type": APPOINTMENT_TYPE,
                                           "notes": {"type": "string", "description": "e.g. nervous patient, toothache lower left"}},
          ["slot_id", "appointment_type"], verified=True),
    _tool("dental_my_appointments", "List the verified patient's upcoming appointments with their booking references.",
          "GET", "/dental/appointments", {}, [], verified=True),
    _tool("dental_reschedule_appointment", "Move one of the verified patient's appointments to a new slot, after confirming.",
          "POST", "/dental/appointments/{booking_ref}/reschedule",
          {"booking_ref": {"type": "string", "description": "e.g. BK-7001"}, "new_slot_id": {"type": "string"}},
          ["booking_ref", "new_slot_id"], verified=True),
    _tool("dental_cancel_appointment", "Cancel one of the verified patient's appointments, after warning about any late cancellation fee.",
          "POST", "/dental/appointments/{booking_ref}/cancel",
          {"booking_ref": {"type": "string", "description": "e.g. BK-7001"}, "reason": {"type": "string"}},
          ["booking_ref"], verified=True),
    _tool("dental_my_cover", "The verified patient's Oakhaven Dental Insurance level, limits used and left, waiting periods, and Care Plan.",
          "GET", "/dental/cover", {}, [], verified=True),
    _tool("dental_estimate_cost", "Price of a treatment and what the verified patient's insurance and Care Plan pay, with what is left to pay.",
          "GET", "/dental/estimate", {"treatment": TREATMENT}, ["treatment"], verified=True),
    _tool("dental_claim_status", "Status of one of the verified patient's dental insurance claims (numbers start with DC).",
          "GET", "/dental/claims/{claim_id}", {"claim_id": {"type": "string", "description": "e.g. DC-5531"}}, ["claim_id"], verified=True),
    # general information on the dental mock, no verification needed
    {"name": "dental_claim_documents", "description": "List the documents a patient must send with a dental insurance claim.",
     "method": "GET", "url": "{mock}/dental/claim-documents",
     "parameters": {"type": "object", "properties": {"claim_type": {"type": "string", "enum": ["dental"],
                                                                    "description": "always dental"}}, "required": ["claim_type"]},
     "requires_verification": False, "is_verification": False, "timeout_s": 8},
]

DENTAL_SKILLS = [
    {"name": "Book a dental appointment", "description": "The caller wants to book a check-up, hygiene, new patient, treatment or sedation consultation appointment",
     "instructions": ("1. Ask whether they are already an Oakhaven patient. If yes, dental_verify_patient. If not, collect first name, last name, "
                      "date of birth, mobile and preferred practice, then dental_register_patient; new patients book a new_patient_exam.\n"
                      "2. Ask which practice and when suits, then dental_find_slots and offer up to three slots.\n"
                      "3. Read back the appointment type, practice, day, date, time and price guide, and wait for a yes before dental_book_appointment.\n"
                      "4. Give the booking reference and mention that cancelling with less than 48 hours' notice costs a fee."),
     "required_tools": ["dental_verify_patient", "dental_register_patient", "dental_find_slots", "dental_book_appointment"], "escalate_when": ""},
    {"name": "Change or cancel an appointment", "description": "The caller wants to move or cancel an appointment they already have",
     "instructions": ("1. dental_verify_patient, then dental_my_appointments and confirm which appointment.\n"
                      "2. If it is less than 48 hours away, say a late cancellation fee of £30 (£60 for appointments over 45 minutes) "
                      "applies, and ask whether they still want to go ahead.\n"
                      "3. To move it: dental_find_slots, offer slots, read the new one back, then dental_reschedule_appointment.\n"
                      "4. To cancel: confirm, then dental_cancel_appointment and say whether a fee was charged."),
     "required_tools": ["dental_verify_patient", "dental_my_appointments", "dental_find_slots", "dental_reschedule_appointment", "dental_cancel_appointment"],
     "escalate_when": "The caller disputes a late cancellation fee."},
    {"name": "Dental emergency", "description": "The caller has toothache, swelling, bleeding, or a broken or knocked-out tooth",
     "instructions": ("1. First ask whether there is swelling that makes it hard to breathe or swallow, swelling spreading to the eye or neck, "
                      "bleeding that has not stopped after 20 minutes of pressure, or a head injury. If yes, tell them to call 999 or go to A&E now.\n"
                      "2. Otherwise search knowledge for the first-aid advice for their problem and give it in short steps.\n"
                      "3. Offer the earliest emergency appointment: dental_find_slots with appointment_type emergency at their practice, "
                      "dental_verify_patient or dental_register_patient, read it back, then dental_book_appointment. It costs £85.\n"
                      "4. Never diagnose or recommend a medicine; a pharmacist can advise on pain relief."),
     "required_tools": ["dental_find_slots", "dental_verify_patient", "dental_register_patient", "dental_book_appointment"],
     "escalate_when": "No emergency slot is free today and the caller is in severe pain."},
    {"name": "Check cover and estimate a cost", "description": "The caller asks what their dental insurance or Care Plan covers, or what a treatment will cost them",
     "instructions": ("1. dental_verify_patient.\n2. For a treatment, dental_estimate_cost; otherwise dental_my_cover.\n"
                      "3. Say the price, what the insurance and Care Plan pay, and what is left for the patient; mention any waiting period "
                      "and when it ends.\n4. For treatment over £300 suggest a pre-treatment estimate. Never promise that a claim will be paid."),
     "required_tools": ["dental_verify_patient", "dental_my_cover", "dental_estimate_cost"], "escalate_when": ""},
    {"name": "Check a dental claim", "description": "The caller asks about a dental insurance claim",
     "instructions": ("1. dental_verify_patient, then ask for the claim number (it starts with DC).\n2. dental_claim_status and explain the status, "
                      "what was paid and the note. If more information is needed, say exactly what to send and how.\n"
                      "3. If the claim was declined, explain the reason and that they can ask for a review within 8 weeks."),
     "required_tools": ["dental_verify_patient", "dental_claim_status"],
     "escalate_when": "The caller disputes a declined claim or asks for a review."},
]


DENTAL = Kit(
    key="dental",
    agent_name="Oakhaven Dental Assistant",
    description=("Front desk for Oakhaven Dental Care, a UK private dental group: books, moves and cancels appointments, triages dental "
                 "emergencies, explains treatments and prices, checks dental insurance and Care Plan cover and claims, and answers "
                 "practice, aftercare and sedation questions."),
    category="Dental care",
    persona={"name": "Maya (Oakhaven Dental)", "description": "Oakhaven Dental Care front desk",
             "greeting": "Thank you for calling Oakhaven Dental Care, this is Maya.",
             "disclosure": "I'm a virtual assistant, and this call may be recorded for quality. How can I help today?",
             "style": "Warm, calm and reassuring, in British English. Short sentences, one question at a time. Read dates, times "
                      "and prices slowly, and read booking references back letter by letter."},
    policy={
        "rules": ["Verify the patient with patient ID and date of birth, or register them as a new patient, before booking, moving or "
                  "cancelling an appointment, or discussing their cover, estimates or claims.",
                  "Before booking, moving or cancelling, read the details back and wait for a yes.",
                  "Quote prices only from approved knowledge or tools, and say 'from' when a price starts at a figure.",
                  "When someone describes a dental emergency, first ask about swelling, breathing, swallowing and bleeding."],
        "never": ["Never diagnose a dental problem or recommend a medicine or a dose.",
                  "Never promise that insurance will pay for a treatment.",
                  "Never discuss another patient's appointments, cover or claims."],
        "escalate_when": ["The caller wants to make a complaint.",
                          "The caller disputes a declined claim or a fee, or asks for a review.",
                          "The caller asks to speak to a person.",
                          "The caller is in severe pain and no emergency appointment is free today."],
        "handoff_message": "I'm passing you to our patient care team, who will have the details so you won't need to repeat yourself.",
        "holding_message": "A member of our patient care team will be with you shortly. Thank you for waiting.",
    },
    knowledge=sorted(DENTAL_KNOWLEDGE.glob("*.md")),
    tools=DENTAL_TOOLS,
    skills=DENTAL_SKILLS,
    mock=True,
    voice_pipeline="realtime",  # one OpenAI connection instead of Deepgram speech-to-text and text-to-speech
    use_cases=load_use_cases(DEMO_DIR / "dental" / "use-cases.md"),
    chats=[
        Chat("Check-up price", ["How much is a routine check-up?"], "Examinations and hygiene prices", {0: [r"£?55"]}),
        Chat("Cancellation policy", ["What is your cancellation policy?"], "Cancellation policy", {0: [r"48hours"]}),
        Chat("Saturday opening", ["Are the Manchester and Bristol practices open on Saturdays?"], "Opening hours", {0: [r"9am|1pm"]}),
        Chat("Knocked-out tooth", ["I knocked out my adult front tooth playing football. What should I do?"], "Knocked-out adult tooth", {0: [r"milk"]}),
        Chat("Major waiting period", ["How long is the waiting period before dental insurance covers a crown?"], "Waiting periods", {0: [r"12-?months?"]}),
        Chat("Whitening not covered", ["Does the dental insurance cover teeth whitening?"], "does not cover", {0: [r"cosmetic|notcover"]}),
        Chat("Sedation", ["I'm very nervous. Can I have IV sedation, and how much is it?"], "Sedation", {0: [r"£?295"]}),
        Chat("Red flags", ["My face is swollen and it's spreading to my eye. What should I do?"], "999", {0: [r"999|A&E"]}),
        Chat("Complaint escalates", ["I want to make a complaint about my treatment."], escalates=True),
        Chat("Book as Priya", ["I'd like to book a hygiene appointment at Leeds, please.", "Yes, my patient ID is OD-10231 and my date of birth is 12 April 1988.",
                               "The first slot is fine.", "Yes, please book it."], expect={3: [r"BK-\d+"]}, needs_model=True),
        Chat("Crown estimate as Priya", ["How much would a crown cost me with my insurance? My patient ID is OD-10231, date of birth 1988-04-12."],
             expect={0: [r"795"]}, needs_model=True),
        Chat("Claim DC-5560 as Tom", ["What's the status of claim DC-5560? I'm patient OD-10457, born 30 September 1975."],
             expect={0: [r"receipt"]}, needs_model=True),
    ],
)

KITS = {k.key: k for k in (DENTAL,)}
