---
title: Oakhaven Dental Assistant - use cases
category: Dental care
---

Use cases for Oakhaven Dental Care (fictional, synthetic). Load them into any agent with:
`python scripts/import_use_cases.py --agent "<agent name>" --file scripts/demo/dental/use-cases.md`

## Book an appointment
Existing patients verify, new patients register; offer slots, read back, book, give the reference.

Channels: voice, chat
Sample phrases:
- I'd like to book a check-up at the Leeds practice.
- I'm new, can I register and see a dentist?
- Can I book a scale and polish on a Saturday in Manchester?
Demo callers:
- Priya Shah | OD-10231 | 12 April 1988 | Book a hygiene appointment in Leeds next week
- Sam Taylor (new patient) | none yet | any | Register (any name, date of birth and mobile) and book a new patient exam in Bristol

## Move or cancel an appointment
Find the booking, warn about the 48-hour late fee, then move or cancel.

Channels: voice, chat
Sample phrases:
- I need to cancel my next appointment.
- Can I move my check-up to a later date?
Demo callers:
- Grace Ellison | OD-10822 | 2 November 1994 | Cancel her hygiene visit (the next free slot in Bristol): under 48 hours, so the £30 fee applies
- Tom Walsh | OD-10457 | 30 September 1975 | Move his Manchester check-up (more than 48 hours away: no fee)

## Dental emergency
Red flags first (999 / A&E), then first aid from knowledge and the earliest £85 emergency slot.

Channels: voice, chat
Sample phrases:
- I've got terrible toothache and my face is swollen.
- My son knocked his front tooth out playing football.
- My crown just fell off.
- It's still bleeding after my extraction.
Demo callers:
- Priya Shah | OD-10231 | 12 April 1988 | Toothache since yesterday, no swelling: book today's emergency slot in Leeds

## Treatments and prices
Price list, what is included, and which practices offer implants, aligners and sedation.

Channels: voice, chat
Sample phrases:
- How much is a check-up?
- What does a root canal on a molar cost?
- Do you do implants in Bristol?
- How much is teeth whitening?

## Cover check and cost estimate
Insurance level, limits left, waiting periods and Care Plan discount; what the patient pays.

Channels: voice, chat
Sample phrases:
- How much would I pay for a crown with my insurance?
- What does my dental insurance cover?
- How much of my annual limit have I used?
Demo callers:
- Priya Shah | OD-10231 | 12 April 1988 | Crown: £795, but major treatment is in its waiting period until 1 July 2027
- Tom Walsh | OD-10457 | 30 September 1975 | Molar root canal: Level 3 pays 80% up to his remaining limit
- Grace Ellison | OD-10822 | 2 November 1994 | Care Plan Plus: what's included and 15% off a filling

## Claim status
Status, amount paid and next step; a disputed decline escalates.

Channels: voice, chat
Sample phrases:
- What's happening with my claim DC-5560?
- Why was my whitening claim declined?
Demo callers:
- Tom Walsh | OD-10457 | 30 September 1975 | DC-5531 paid £316; DC-5560 needs the itemised receipt; DC-5512 declined (cosmetic): dispute it to escalate

## Care Plans and insurance
Explain Essential and Plus Care Plans, insurance levels, waiting periods, joining and cancelling.

Channels: voice, chat
Sample phrases:
- What's the difference between the Care Plan and dental insurance?
- How long before insurance covers a filling?
- Are children covered on the Care Plan?

## Aftercare
The practice's aftercare sheet for extractions, fillings, root canals, whitening and hygiene.

Channels: voice, chat
Sample phrases:
- What should I avoid after having a tooth out?
- My filling still feels sensitive, is that normal?

## Practice information
Addresses, opening hours, out-of-hours line, parking and accessibility.

Channels: voice, chat
Sample phrases:
- Are you open on Saturdays in Leeds?
- Is there parking at the Manchester practice?
- Is the Bristol practice wheelchair accessible?

## Nervous patients and sedation
Support for anxious patients and IV sedation rules and price.

Channels: voice, chat
Sample phrases:
- I'm terrified of the dentist, can you help?
- Can I have sedation for my wisdom tooth?

## Complaints and records
Complaints escalate to the patient care team; how to get a copy of records.

Channels: voice, chat
Sample phrases:
- I want to make a complaint about my treatment.
- How do I get a copy of my dental records?
