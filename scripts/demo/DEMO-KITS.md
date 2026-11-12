# Demo kit: Oakhaven Dental

A fictional UK dental group with ready-made knowledge, use cases, tools and test lines, built next to the Northgate Health agents (Customer Care, Health Cover Sales, Claims & Pre-authorisation) so the front desk can route dental callers to it. Every person and record is synthetic.

| Kit | Knowledge to upload | Use cases | Tools |
|---|---|---|---|
| `dental` (Oakhaven Dental Care, UK) | `dental/oakhaven-dental-knowledge-okf.zip` (3 OKF articles in one upload) or the 3 files in `dental/knowledge/` | `dental/use-cases.md` (11) | 11 `dental_*` tools, all on the mock patient system `demo_kits.py` (or `scripts/dev.py`) serves |

## Demo flow: build the dental agent on stage

1. `python scripts/dev.py` (terminal 1).
2. In the Studio: **Agents → New agent**, e.g. *Dental Care agent*, in *Northgate Health · Member & Sales Services*.
3. Terminal 2, and leave it running (the booking, cover and claim tools call the mock it serves):
   ```
   python scripts/demo_kits.py dental --agent "Dental Care agent"
   ```
   It adds the 11 tools, 5 skills, the *Maya (Oakhaven Dental)* persona, the guardrails and the 11 use cases to that agent's **draft**. It does not touch knowledge and does not publish. **Reload the editor page** afterwards (an open editor would otherwise save its old draft over it).
4. **Knowledge → Upload** → `oakhaven-dental-knowledge-okf.zip`: three rows with the *OKF* badge, ticked. **Test search** `knocked out tooth`.
5. **Save draft → Publish**. Only the published version takes calls.
6. **Test call** → **Type** or **Talk**, **Technical details** on.

Use cases alone, for any agent and any file in the same format:
```
python scripts/import_use_cases.py --agent "Dental Care agent" --file scripts/demo/dental/use-cases.md
```
`--replace` also deletes the agent's use cases that are not in the file; `--dry-run` only parses.

Everything prepared in one go instead: `python scripts/demo_kits.py dental` builds and publishes the *Oakhaven Dental Assistant* in `northgate-health` (the default `--tenant`), so a Test call **Full flow** or a phone number on the front desk routes "I need a dental check-up" to it. Rehearse with no keys and no cost: `python scripts/demo_kits.py dental --check`.

## Dental test lines

Demo patients: **Priya Shah** OD-10231, born 12 April 1988 (Leeds, insurance Level 2 since July 2026); **Tom Walsh** OD-10457, born 30 September 1975 (Manchester, Level 3, three claims); **Grace Ellison** OD-10822, born 2 November 1994 (Bristol, Care Plan Plus, hygiene visit in the next free slot). New callers can register with any name.

| Shows | Caller says | Expected |
|---|---|---|
| Knowledge: prices | "How much is a check-up?" | £55 (new patient exam £75) |
| Knowledge: hours | "Are you open on Saturdays in Leeds?" | Leeds no; Manchester and Bristol 9am to 1pm |
| Knowledge: safety | "My face is swollen and it's spreading to my eye." | Call 999 or go to A&E now |
| Knowledge: first aid | "I knocked my front tooth out playing football." | Hold it by the crown, keep it in milk, come within an hour; offers the £85 emergency slot |
| Knowledge: insurance | "Does insurance cover teeth whitening?" | No, cosmetic treatment is excluded |
| Tool, no login | "What documents do I need to send with a dental claim?" | `dental_claim_documents`: itemised dental bill with procedure codes, … |
| Tools: booking | "Book a hygiene appointment in Leeds" → Priya's ID and date of birth → pick a slot → "yes" | Verifies, offers slots, reads back, books, gives a BK- reference |
| Tools: new patient | "I'm new and want to see a dentist in Bristol" | Registers (name, date of birth, mobile), books a new patient exam (£75) |
| Tools: late fee | Grace: "Cancel my next appointment" | Warns the £30 late fee applies before cancelling |
| Tools: estimate | Priya: "How much would a crown cost me?" | £795; insurance pays nothing until 1 July 2027 (waiting period) |
| Tools: estimate | Tom: "And a root canal on a molar?" | £695; Level 3 pays £556, Tom pays £139 |
| Tools: claim | Tom: "What's happening with DC-5560?" | Needs the itemised receipt |
| Escalation | Tom: "DC-5512 was declined and I want it reviewed." | Explains the cosmetic exclusion, hands over to the patient care team |
| Escalation | "I want to make a complaint." | Hands over |
| Guardrail | "Just tell me insurance will pay for my crown." | Will not promise payment |

## Limits worth knowing

* The mock patient system runs on `127.0.0.1` inside `demo_kits.py` (or `scripts/dev.py`, port 8766): all 11 tools, `dental_claim_documents` included, work only on this machine while it runs, and it resets on every start.
* The Knowledge tab lists every document of the business unit (only ticked ones are used), and the Use cases tab has no file import yet: both need a change proposal.
* The platform's own "verify first" line says "member ID"; Maya asks for the "patient ID" everywhere else.
* The fake LLM (`--check` without `--live`) proves the build, retrieval and escalation, not answer quality.
