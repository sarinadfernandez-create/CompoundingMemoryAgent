### First Iteration: 
Simple task, just have to determine what the proper formatting is for company without any instructions by comparing to the desired result. After a few iterations it did it perfectly every time even on different sentences. So this is a positive signal but this task is super super easy, like a 6 year old could do it easily, so I need to challenge it more. Also, if you look at the agent memory, its very redundant, need better context engineering.
<img width="910" height="585" alt="memory_curve" src="https://github.com/user-attachments/assets/8f2f3d44-1741-4016-bb5f-982b0d7769b7" />

##### Agent memory (self-taught)
```
- Always confirm the target system's field names, value formats (e.g., case, date order, units like cents vs. decimals), and schema before assuming standard conventions.
- Always output customer names in ALL CAPS, dates in DDMMYYYY format, and use the exact field names specified by the target system's schema.
- Use the exact JSON field names specified by the client/system (e.g., `"customer"` not `"customer_name"`), as renaming fields breaks downstream processing.
- When representing monetary amounts, store them in cents as an integer under the key `amount_cents` (not `amount`) to make the unit explicit.
- Output a JSON object with customer name in ALL CAPS, date in DDMMYYYY format, and amount converted to integer cents — never output null when the required data is present in the message.
```

### Second Iteration: 
**Switched to a harder task:** the agent is an _onboarding specialist_ (incorporating, banking, setting up new businesses). For each customer message it produces a structured plan: actions, open questions, risks. A **reviewer** compares the draft to a reference of what thorough coverage would look like and writes category-tagged lessons about what was missed. A separate **curator** agent then merges those lessons into a structured markdown playbook—creating a new section every time a new category emerges.

**Note:** The reviewer would be based on some combination of user feedback, existing skill documents for common skills, etc. RN in this iteration its just made up.

**Next steps:** Came out with good results but not really any evaluation metric, so make sure to include that next time. Also this is redundant with info that Claude already has, so a waste of context. Tackle that after eval metric.

##### Output:
```
Incorporation
- For a solo founder, clarify upfront whether they want the LLC taxed as a disregarded entity (default) or elect S-corp or C-corp treatment, since tax classification significantly impacts filing complexity and liability structure.
- For venture-backed startups planning to raise angel rounds, default to Delaware C-Corp incorporation rather than presenting multiple entity options—this aligns with investor expectations and avoids later restructuring costs.
Compliance & Tax
- Avoid over-scoping the onboarding plan with items like professional liability insurance, home office lease verification, and NYC-specific permits unless the customer's industry, lease terms, or business model explicitly raises those risks.
- Focus discovery questions on core operational facts (name, address, revenue, activity type) rather than speculative scenarios like future employees or multi-state expansion; add questions only when the customer's stated facts warrant them.
- Prioritize 409A valuation timing carefully: while recommended before an angel round, ensure it happens after—not before—stock issuance and 83(b) filing to avoid valuation conflicts with the initial cap table.
- When a founder spans multiple tax jurisdictions, flag the need for cross-border tax counsel upfront to address double-taxation risks and treaty implications, rather than treating tax residency as an isolated incorporation question.
- Sales tax nexus and compliance obligations scale with revenue and customer geography; clarify the customer's target market early to scope whether sales tax registration and filing will be required.
- Identify and explicitly preserve tax attributes (NOLs, credits, basis step-ups) that may survive or be lost depending on conversion structure; coordinate with a tax advisor to align the chosen structure with the customer's tax position, not just incorporation mechanics.
- When a business has operated informally for an extended period with revenue, always prioritize a CPA review of back-tax obligations and personal liability exposure before entity formation—retroactive incorporation does not automatically absolve prior personal tax filings or self-employment tax owed.
- GDPR and data residency obligations for EU customer data must be assessed independently of entity formation—personal data handling, storage location, and consent mechanics are separate compliance domains with their own audit and remediation timelines.
Equity & Cap Table
- When issuing founder stock with vesting, immediately file 83(b) elections within 30 days or face unavoidable year-by-year taxation on equity appreciation—this deadline has no extensions and should be flagged as a critical milestone.
International / KYC
- For non-resident founders, proactively identify and recommend non-resident-friendly banking partners (Mercury, Brex, Wise) early, rather than assuming standard US banks will accept the application.
- For SaaS with significant EU customer concentration, VAT registration and OSS (One-Stop Shop) scheme eligibility must be determined early and mapped by customer location and revenue threshold—non-compliance carries cascading penalties and creates accounting complexity that is difficult to unwind retroactively.
Conversion / Restructuring
- Explicitly identify and document the conversion structure (statutory conversion, F-reorganization, or merger) early, as each has different tax and legal consequences; do not default to asset transfer without assessing whether a tax-deferred reorganization is available and preferable.
- Systematically audit existing contracts, customer agreements, and IP assignments for anti-assignment or change-of-control clauses before executing the conversion; obtain required consents upfront rather than discovering blocking provisions during or after entity transition.
Banking
- Payment processor migration (e.g., Stripe account transition from personal to business) should be planned with a cutover window and backup processor readiness—account review or verification friction during migration can disrupt revenue collection and must be de-risked in advance.
```

### Third Iteration: including eval metric
The warm (with context/memory) had good results, but don't have results for cold. Did a good job reducing the size of the playbook

##### Output:
```
## Incorporation
- When a founder forms an entity in one state but operates in another, always include foreign qualification in the home state as a required step, not an optional one.

## Equity & cap table
- Always flag the double-taxation trade-off of a C-Corporation structure so founders make an informed choice, even when the C-Corp is clearly the right answer for venture-backed companies.

## Compliance & tax
- Always flag US sales tax nexus obligations for SaaS products — once revenue thresholds are crossed in certain states, sales tax collection and remittance may be required, regardless of whether the founder is a US resident.
- Always ask whether the LLC has net operating losses or other tax attributes worth preserving, as the choice of conversion structure can determine whether those attributes survive or are extinguished.

## Conversion / restructuring
- When advising on LLC-to-C-Corp conversions, always explicitly flag the F-reorganization (F-reorg) as a distinct structural option alongside statutory conversion and merger, since it often preserves tax attributes such as NOLs and EINs and is frequently the preferred path for venture-bound startups.

## International / KYC
- When a business has EU customers, always request revenue broken down by country rather than relying on aggregate EU figures, as per-country VAT thresholds and OSS eligibility assessments require country-level data to be accurate.
```

### Fourth iteration: properly including eval metric
Uh oh, cold actually did better than warm...why?
few ideas:
- Sonnet 4.6 is enormously capable on this task domain on its own. maybe the instructions detract from the quality bc they are not all-inclusive.
- Need some way to make the model reliant on sonnets reasoning except when specific client info is needed (preferences, information, names)
- Maybe have context limited to client specific things so it doesn't take away from Claude.
- Also note that the warm output is tighter, so there is some benefit (actions/questions/risks):
	- warm -> 15/12/10
	- cold -> 20/14/12

##### Output:
```
Customer message: I'm a software developer based in India. I want to start a US business for my consulting work, and I already have a few US clients who have been paying me directly via wire transfer over the past few months. I want to do this properly. Help me? ──────────────────────────────────────────────────────────────────────── RUN 1: COLD (no playbook — what the model knows on its own) ──────────────────────────────────────────────────────────────────────── { 
"actions": [ "Determine the best US entity type for a non-resident founder \u2014 a Wyoming or Delaware Single-Member LLC is typically the most practical choice for a solo Indian software consultant due to low costs, pass-through taxation, no US tax residency requirement for ownership, and strong legal protections; present both options with fee comparison", "Collect all required information for entity formation: chosen state, desired LLC name (plus 2-3 alternates), registered agent details, principal business address (a US virtual office address is acceptable), and founder's personal details including passport copy and Indian address", "Engage a registered agent service in the chosen state (Wyoming ~$50/yr, Delaware ~$50\u2013100/yr) since the founder has no physical US presence \u2014 this is legally required", "File Articles of Organization with the chosen state's Secretary of State and obtain the stamped/approved formation documents (Certificate of Organization or Formation)", "Draft a Single-Member LLC Operating Agreement tailored for a non-resident single-member LLC \u2014 this is critical for banking and legitimacy", "Apply for a US Employer Identification Number (EIN) via IRS Form SS-4; since the founder is a non-resident individual without an SSN/ITIN, the application must be submitted by fax or mail (or phone for international applicants) directly to the IRS \u2014 clarify that an SSN is NOT required to obtain an EIN as a foreign owner", "Open a US business bank account \u2014 research banks and fintechs that support non-resident-owned LLCs (Mercury, Relay, Wise Business, or Brex are strong options as they do not require in-person visits); prepare to submit: EIN confirmation letter, Articles of Organization, Operating Agreement, passport, and proof of address", "Set up a US virtual office address (e.g., via Regus, iPostal1, or similar) if not already done \u2014 needed for state registration, banking, and professional appearance; avoid using a registered agent address for banking as some banks reject this", "Retroactively address the prior months of payments received directly as an individual: advise the founder to document these carefully for tax purposes and understand the distinction going forward \u2014 payments received before the LLC existed are personal income, not LLC income", "Instruct existing US clients to update their payment details to the new LLC name and US bank account once banking is established; provide a template notification letter", "Set up invoicing under the LLC name using a tool like Wave, FreshBooks, or QuickBooks \u2014 ensure invoices reference the LLC name, EIN, and new US bank details", "Advise on US tax obligations: a single-member LLC owned by a non-resident alien is a 'disregarded entity' for US tax purposes; the LLC itself files no separate US federal income tax return, BUT the foreign owner must file Form 1040-NR if effectively connected income exists, and clients paying the LLC over $600/year must issue a Form 1099-NEC unless a W-8BEN-E is provided", "Prepare and provide a W-8BEN-E template for the founder to send to each US client \u2014 this certifies foreign status, may reduce or eliminate US withholding tax under the India-US tax treaty, and prevents clients from withholding 30% of payments", "Advise on Indian tax obligations: all income earned through the US LLC will still be taxable in India as the founder is an Indian tax resident; income must be reported in Indian ITR filings; consult a CA in India familiar with foreign income and FEMA regulations", "Assess FEMA (Foreign Exchange Management Act) compliance: receiving money into a foreign LLC account and then remitting to India must comply with RBI/FEMA rules; advise consulting an Indian CA or CS familiar with cross-border structures to ensure the remittance pathway (LLC profits \u2192 founder's Indian bank account) is compliant", "Recommend the founder obtain a dedicated business phone number and US-facing email for professional correspondence with clients", "Set up a simple bookkeeping system from day one to track all LLC income and expenses separately from personal finances \u2014 this is critical for piercing-the-corporate-veil protection and tax compliance", "Advise on annual compliance requirements: (a) State annual report/franchise tax filing in chosen state, (b) FinCEN Beneficial Ownership Information (BOI) report \u2014 newly formed LLCs in 2024/2025 must file within 90 days of formation, (c) maintaining a registered agent, (d) renewing virtual office if used", "Flag the new FinCEN BOI reporting requirement under the Corporate Transparency Act \u2014 the founder as a non-US person must submit passport details as the beneficial owner; walk through this process", "Discuss whether the founder needs a US ITIN (Individual Taxpayer Identification Number) in addition to the LLC's EIN \u2014 this may be needed for filing 1040-NR or claiming treaty benefits; initiate Form W-7 process if required" ], 

"questions": [ "Which US state do you prefer for formation \u2014 Wyoming (cheapest, most privacy-friendly, low annual fees) or Delaware (more prestigious, preferred by investors, slightly higher cost)? Do you have any preference or future plans like raising investment that might influence this?", "Do you have a specific business name in mind for the LLC, and do you have 2-3 backup names in case your first choice is already taken?", "Do you currently have a US address of any kind, or will you need us to help set up a virtual office address in the US?", "Can you confirm your Indian residential address and provide a copy of your passport for entity formation and banking KYC purposes?", "Have you already applied for or received a US EIN or ITIN previously for any reason?", "How many US clients do you currently have, and are they individuals or companies? Do they currently have you on a W-9 or any tax form, or have they been paying you informally without any tax documentation?", "Roughly what is your annual revenue from these US clients? This helps us assess withholding tax risk and whether any clients may have already under-withheld on payments made to you as an individual", "Are any of your US clients likely to issue you a 1099 for the payments already made this year? If so, those would be under your personal name, not the LLC \u2014 we need to plan for this", "Do you have an Indian CA or chartered accountant who handles your personal taxes and is familiar with foreign income and FEMA/RBI regulations? If not, we can refer one", "Do you plan to keep the business as a solo consultancy, or do you anticipate hiring employees or contractors (US or Indian) in the future?", "Do you anticipate needing to travel to the US for client meetings? If so, we should discuss visa considerations (B-1 business visitor vs. other visa types) and ensure your LLC structure does not inadvertently create complications", "Do you want the LLC to have a business bank account in the US only, or also a multi-currency account that can hold USD and convert to INR easily for personal remittances?", "Are any of your clients in regulated industries (healthcare, finance, defense) that might impose additional contractor compliance requirements on your LLC?", "What is your timeline \u2014 do you have invoices pending or contracts being signed imminently that require the LLC to be in place?" ], 

"risks": [ "FEMA/RBI Compliance Risk: Receiving income into a foreign-owned LLC and repatriating profits to India as the owner must be done in a FEMA-compliant manner. Routing income through a US LLC without proper documentation or RBI-compliant remittance channels could attract regulatory scrutiny. An Indian CA familiar with FEMA and cross-border structures is essential.", "Retroactive Payment Risk: Payments already received by the founder personally from US clients over the past months may have created US tax nexus or withholding obligations. If any US client has been treating the founder as a US person and plans to issue a 1099, the founder may face unexpected US filing obligations or penalties. This must be assessed and addressed proactively.", "Withholding Tax Risk (30%): Until a valid W-8BEN-E is on file with each US client, those clients are technically required to withhold 30% of payments to foreign persons. If they have not been withholding, they may be liable, and the IRS could pursue the underlying tax from the founder. Remedying this quickly with W-8BEN-E forms is critical.", "FinCEN BOI Non-Compliance Risk: Newly formed LLCs must file a Beneficial Ownership Information report with FinCEN within 90 days. Failure to file carries significant civil and criminal penalties ($500/day up to $10,000 and up to 2 years imprisonment). As a non-US person, the founder must provide passport details \u2014 this must not be overlooked.", "Banking Rejection Risk: Many traditional US banks will not open accounts for non-resident-owned LLCs without in-person visits. Even fintech-friendly banks (Mercury, Relay) have KYC processes that may reject applicants based on country of residence, nature of business, or incomplete documentation. Have a tiered list of banking options ready and prepare documentation thoroughly.", "Permanent Establishment / US Tax Nexus Risk: If the founder's activities are deemed to constitute a US trade or business (e.g., performing services that are considered 'effectively connected income'), the LLC income may be subject to US federal income tax, requiring a 1040-NR filing. The structure must be reviewed to ensure the India-US tax treaty is being leveraged appropriately.", "Commingling of Pre-LLC Income Risk: Income received before the LLC was formed is personal income, not LLC income. If clients issue 1099s under the founder's personal name for the full year, there will be a mismatch between personal and LLC income records. This needs to be carefully tracked and disclosed in Indian ITR filings.", "State Tax Nexus Risk: Even though the LLC is registered in Wyoming or Delaware, if the founder is performing services for clients in specific US states, some states (e.g., California, New York) may assert tax nexus or require foreign qualification. This is a lower risk for a remote software consultant but should be monitored especially if US travel for client work occurs.", "Visa and Immigration Risk: Performing substantive work for US clients while in the US on a tourist/B-2 visa is prohibited. If the founder travels to the US for client meetings, they must use a B-1 business visitor visa and must not perform actual billable work while on US soil. Owning a US LLC does not grant any US work authorization.", "Intellectual Property Risk: Without a proper consulting agreement in place with each client, IP ownership of work product may be ambiguous or default to the client. Ensure all client contracts are in the LLC's name, clearly define IP ownership, limitation of liability, and governing law.", "Double Taxation Risk: Without proper treaty planning and documentation, the founder could face taxation on the same income in both the US and India. While the India-US DTAA (Double Tax Avoidance Agreement) provides relief, it must be actively claimed and documented \u2014 it is not automatic.", "Operational Continuity Risk: If the registered agent, virtual office, or annual state filings lapse, the LLC could be administratively dissolved, which would invalidate contracts and banking relationships. Set up calendar reminders and auto-renewals for all annual compliance obligations from day one." ] } Coverage of reference: 94% (16/17 items) 

──────────────────────────────────────────────────────────────────────── RUN 2: WARM (with the self-built playbook from 5 prior cases) ──────────────────────────────────────────────────────────────────────── { 
"actions": [ "Determine the optimal US entity type for a non-resident founder: a Wyoming or Delaware single-member LLC is typically the starting point for a solo consultant, but evaluate C-Corp if VC funding or equity compensation is anticipated \u2014 schedule a scoping call to confirm business goals before filing.", "Prepare and file Articles of Organization (LLC) or Certificate of Incorporation (C-Corp) in the chosen state, appointing a registered agent in that state as required for non-resident founders.", "Obtain an EIN (Employer Identification Number) from the IRS via Form SS-4 \u2014 non-residents cannot use the online portal and must apply by fax or phone; plan for a 2\u20134 week processing window.", "Open a US business bank account \u2014 research banks and fintechs (e.g., Mercury, Relay, Brex) that support non-resident-owned US entities and do not require in-person branch visits, as traditional banks often do.", "Collect and review all KYC/AML documentation required for non-resident founders: valid passport, proof of address in India, ownership/control certification, and entity formation documents.", "Once the business bank account is open, migrate existing US clients from paying you personally via wire transfer to paying the new US business entity \u2014 update invoices, contracts, and payment instructions accordingly.", "Review and update or draft fresh consulting agreements with existing US clients that name the new US entity as the contracting party, including proper governing law, IP assignment, and liability clauses.", "Register for a US business address or virtual office if required by the bank or clients (distinct from the registered agent address).", "Assess US federal tax obligations: as a non-resident alien owning a single-member LLC, the entity is by default a disregarded entity for US tax, but income sourcing rules are critical \u2014 engage a US CPA familiar with non-resident taxation to determine whether income is US-source and whether withholding or treaty provisions apply.", "Assess Indian tax obligations: income earned through the US entity may still be taxable in India depending on DTAA (Double Taxation Avoidance Agreement) provisions, PE (permanent establishment) risk, and FEMA/RBI remittance rules \u2014 engage an India-based CA alongside the US CPA.", "Determine whether the business activities create a permanent establishment risk in the US or India under the India-US tax treaty.", "Set up a US-compatible accounting system (e.g., QuickBooks Online, Xero) from day one to segregate business income and expenses, facilitate year-end tax filings, and support any future banking or investor due diligence.", "Evaluate payment processor needs: if clients will pay via ACH, credit card, or platforms like Stripe, set up business accounts on those processors linked to the new business bank account rather than personal accounts.", "File annual compliance requirements: state annual reports/franchise tax (varies by state), IRS Form 5472 + Form 1120 (required for foreign-owned single-member LLCs even if no US tax is owed) \u2014 calendar these deadlines immediately.", "Consider whether to elect S-Corp or C-Corp tax treatment in the future; note that S-Corp status is not available to non-resident aliens, so this option is categorically unavailable \u2014 do not pursue it." ], 

"questions": [ "What are your primary goals for the US entity \u2014 consulting income only, or do you anticipate raising investment, hiring US employees, or issuing equity in the future? This determines LLC vs. C-Corp.", "Which US states are your current clients located in? This may trigger state-level tax nexus or registration obligations beyond the state of incorporation.", "Have you already been reporting and paying tax in India on the income received from US clients over the past few months? This affects how we structure the transition and back-compliance.", "Do you hold or plan to apply for any US visa (e.g., B-1, O-1, E-2)? Understanding your visa status is critical before discussing any US-based operational activities.", "Will you ever perform any of your consulting work physically while present in the US (e.g., on-site at a client, at a conference)? This has direct visa and tax implications.", "What is the approximate annual revenue from your US clients, and can you break it down by client and state? This is needed to assess nexus and tax filing obligations.", "Do you have any existing net operating losses, deferred revenue, or other tax attributes from prior years that need to be considered in structuring the new entity?", "Do you have EU-based customers now or anticipated in the near future? If so, we will need country-level revenue figures to assess VAT/OSS obligations.", "Do you have a US Individual Taxpayer Identification Number (ITIN) or SSN? This affects the EIN application process and treaty benefit claims.", "Are your existing client contracts in your personal name? Do those clients need to formally novate or consent to the assignment of those contracts to the new entity?", "Do any of your existing clients withhold US taxes (e.g., under backup withholding or 30% NRA withholding) from payments to you? If so, a W-8BEN-E will need to be provided to them once the entity is established.", "What is your preferred timeline for having the entity operational and banking live?" ], 

"risks": [ "VISA RISK \u2014 CRITICAL: Owning a US LLC or corporation is legally distinct from being authorized to work in the US. If you ever travel to the US and perform consulting services (even remotely logging in to work for US clients while physically in the US), you may require an appropriate work visa (e.g., B-1 has limited scope, and general work requires O-1, TN, or other visas). This must be reviewed with an immigration attorney before any US travel.", "BACK-COMPLIANCE RISK: Income received from US clients in your personal name over the past few months may have created US tax filing obligations (Form 1040-NR or treaty-based exemption claims) and/or Indian tax obligations. Failure to address this before transitioning to the new entity could result in penalties.", "PERMANENT ESTABLISHMENT RISK: If the Indian tax authorities determine that your US-facing consulting business constitutes a PE in India (which is likely given you perform the work in India), the income may be fully taxable in India regardless of US entity structure. Improper structuring could result in double taxation rather than tax efficiency.", "FEMA/RBI COMPLIANCE RISK: Receiving foreign remittances in India and routing income through a foreign entity has specific FEMA and RBI reporting requirements. Non-compliance can result in significant penalties under Indian law.", "PAYMENT INTERRUPTION RISK: Migrating existing clients from paying you personally to paying the new business entity is not a mere administrative update \u2014 it requires contract novation, updated banking details, and potentially new W-8 forms. If not managed carefully, payments could be delayed, misdirected, or trigger compliance flags at the client's accounts payable department.", "IRS FORM 5472 RISK: Foreign-owned single-member LLCs are required to file Form 5472 attached to a pro-forma Form 1120 annually, even if the entity has no US-source income or tax liability. Penalties for failure to file are $25,000 per form \u2014 this is a commonly missed obligation for non-resident founders.", "STATE TAX NEXUS RISK: Having US clients in multiple states may have already created sales tax, income tax, or franchise tax nexus obligations in those states, depending on economic nexus thresholds. This exposure predates the new entity and must be assessed.", "EIN DELAY RISK: The EIN application for non-residents via fax/phone can take 2\u20136 weeks. Without an EIN, the bank account cannot be opened and invoicing under the new entity will be delayed \u2014 plan timelines accordingly.", "BANKING REJECTION RISK: Non-resident-owned US entities face higher KYC scrutiny. Traditional US banks frequently reject or delay account opening. Even fintech-friendly banks can request extensive documentation. Have all identity and entity documents prepared and apostilled if required.", "ENTITY TYPE LOCK-IN RISK: Choosing an LLC now is not irreversible, but converting to a C-Corp later (if investors require it) has tax and structural implications. If there is any possibility of raising US venture capital, the entity type decision should be made carefully upfront to avoid a costly conversion process later." ], "open_questions_note": "All questions above should be resolved before filing to ensure the correct entity type, state, and tax structure are selected from the outset." } Coverage of reference: 88% (15/17 items) 

======================================================================== QUANTIFIED IMPROVEMENT (held-out case, same frozen model) ======================================================================Cold : 94% coverage of reference 
Warm : 88% coverage of reference 
Δ : -6 percentage points (purely from self-built memory) 
What the warm plan still misses: 
• [action] Backdated accounting and tax review for prior personal-wire revenue 
• [question] Any existing Indian entity or GST registration to coordinate with
```


### Iteration 5: 
**+23 percentage points from cold to warm!** what did I change:
- The agent serves a single fictional client across five different task types—invoice processing, customer onboarding, international contractor hire, advisor setup, customer dispute. It learns client-specific facts: Helix's banking rails, template versions, approval thresholds, vendor history, past incidents. The held-out test deliberately requires stitching facts from three different task types: 'pay a Brazilian advisor on recurring' needs the international payment rule from the contractor task, the advisor template from the advisor task, and the voice-verify-bank-changes rule from the invoice task. Cold can't synthesize that as those facts aren't anywhere except in this company's institutional knowledge. The warm playbook is the company's institutional knowledge, accumulated and reorganized into retrievable skills. That's the per-customer memory layer.
- Context reduction
	- Asks a router model "given this customer task, which of these sections apply?"
	- Builds a slimmed playbook with only the chosen sections.
	- Feeds that to the working agent.
	- **Note:** This somewhat backfired, the one thing the warm plan missed was involving equity which was what the retriever deemed irrelevant
	
```
Playbook after episode 5:
────────────────────────────────────────────────────────────────────────
## Banking & Payments
- Domestic vendor payments must be made via ACH from the Mercury business account — wire transfers are not permitted (policy established after a 2024 wire fraud incident).
- Helix routes all international payments through Wise, not Mercury — switched in Q2 2024 due to Mercury's international transfer fees; never flag ACH-only as a conflict for cross-border payments.
- Any vendor bank account change request must be voice-verified with the known contact on file using previously verified contact details — contact information provided within the change request itself must never be used.
- Refunds or credits issued to resolve customer disputes must be processed through Mercury and logged in the customer issues tracker (for board reporting) — CRM-only logging is not sufficient.

## Approvals & Routing
- Any Helix spend exceeding $5,000 requires CEO (Marcus) approval before payment is released, regardless of invoice age or vendor relationship.
- Helix routes CS ownership by ARR tier: under $25K → Priya, $25K–$100K → Daniel, over $100K → Marcus is directly involved; always assign the correct CS owner at onboarding based on this tiering.
- Before signing any contractor agreement, the relevant tech lead (e.g., Priya for engineering roles) must review the candidate's background — this step must be included in the hire setup plan.
- All Helix MSAs require a VP-level or above signatory from the customer side; when reviewing any MSA or disputed contract, verify the customer signatory meets this threshold specifically, not just that they had general authority to bind the company.

## Vendor & Customer History
- BioReagents Inc had a pricing dispute with Helix in Q3 2024; all BioReagents invoices must be matched against contracted rates in NetSuite via an open PO before approval.
- Helix mandates a 14-day customer success check-in for all new customers as a churn-mitigation policy instituted after the 2024 first-month churn issue; this must be scheduled at onboarding.
- Helix's 2023 worker misclassification issue established that advisors and contractors must be assessed for 1099-vs-W-2 status based on true independence before engagement begins; this classification check is a required step in onboarding any advisor or contractor.
- Starting Q1 2025, customer disputes are a board-tracked KPI; all disputes must be logged in the dedicated customer issues tracker immediately upon identification, this tracker feeds board reporting and carries a mandatory 14-day resolution SLA.

## Contract Templates
- Always use Helix MSA template v3.2 (not v3.1) for domestic engagements; v3.2 corrected the limitation-of-liability bug and added explicit opt-in auto-renewal language introduced after the 2024 Acme Bio dispute.
- For international contractor engagements, use IC agreement template v2.1 (the international version), which includes W-8BEN-E provisions and a 30-day notice clause — not the domestic MSA template v3.2.
- Scientific advisor agreements must use advisor-specific template v1.4 (not the general MSA v3.2), which includes the IP assignment clause Marcus added after the 2024 patent dispute — using the wrong template risks missing critical IP protections.
- Helix advisor agreements must include a non-compete disclosure requirement covering conflicting advisor positions at other biotechs, and if the advisor will access confidential research, a separate IP/confidentiality addendum is required in addition to the base advisor template v1.4.

## Compliance
- Helix only collects sales tax in California and New York per the 2023 settlement; always confirm the customer's billing state and any nexus implications before invoicing.

## Equity & Cap Table
- Helix's contractor equity policy excludes any contractor engaged for fewer than 6 months from receiving equity — established after the 2023 cap table cleanup and must be reflected in all short-term contractor agreements.
- Helix's default equity grant for Scientific Advisory Board members is 0.05% vesting over the engagement term — apply and document this standard grant automatically rather than escalating it as an open question.

========================================================================
HELD-OUT TEST — International advisor recurring setup (cross-task synthesis)
========================================================================

Request:
  Bringing on Dr. Rafael Costa as a scientific advisor — he's based in Brazil, $3,000/month for 12 months. He just sent over his new bank account details for payment. Set this up.

This test deliberately requires facts learned across multiple
earlier tasks: intl-payment policy (T3), advisor template (T4),
bank-verification policy (T1), Marcus approval threshold (T1).

────────────────────────────────────────────────────────────────────────
RUN 1: COLD  (no Helix playbook — model knows only generics)
────────────────────────────────────────────────────────────────────────
{
  "actions": [
    "Pause all payment setup activity until identity and banking change verification steps are completed \u2014 do not action the new bank account details yet",
    "Confirm Dr. Rafael Costa's engagement with Helix leadership (e.g., CEO, CSO, or whoever sponsors the advisor relationship) via a known internal channel \u2014 not via contact details supplied in the same message as the bank change",
    "Request and review a signed Scientific Advisor Agreement (SAA) before any payment is initiated \u2014 confirm Helix has a standard SAA template and that it has been or will be executed with Dr. Costa",
    "Verify Dr. Costa's identity and tax/legal status: obtain a completed W-8BEN (or equivalent Brazil-to-US cross-border tax form) given he is a Brazil-based foreign national receiving payments from a US entity",
    "Independently verify the new bank account details by calling or video-calling Dr. Costa directly using contact information already on file with Helix (not from the incoming message) \u2014 this is a standard BEC/fraud-prevention step",
    "Confirm the payment method and currency: determine whether payment will be USD wire to a Brazilian account, or via an international payroll/contractor platform (e.g., Deel, Remote, Wise Business) consistent with Helix's existing vendor stack",
    "Check Brazilian legal requirements: payments to a Brazilian resident for advisory services may require compliance with Brazilian tax withholding rules (DARF/IRRF) and potentially a service contract registered locally \u2014 loop in Helix's legal counsel or a Brazil-experienced EOR/contractor platform",
    "Obtain any required conflict-of-interest or IP assignment addenda per Helix's standard advisor onboarding checklist",
    "Once all verification and documentation steps are complete, set up Dr. Costa as a new vendor/contractor in Helix's accounts-payable or contractor management system with the verified banking details",
    "Schedule the first payment to align with the contract start date, and set up 11 subsequent monthly payments with calendar reminders for contract renewal/expiry at month 12",
    "Retain signed agreement, tax forms, and verified banking confirmation in Helix's document management system (e.g., Google Drive, Notion, or equivalent) under the advisor's record"
  ],
  "questions": [
    "Who is the internal Helix sponsor for Dr. Costa's advisory engagement, and can they confirm via Slack/email that this engagement is authorized?",
    "Has a Scientific Advisor Agreement been drafted and signed, or is that still pending?",
    "What payment platform does Helix currently use for international contractors \u2014 Deel, Wise, direct wire, or another vendor?",
    "Does Helix have existing Brazil-specific contractor/payment infrastructure, or is this the first Brazil-based payee?",
    "Has legal counsel reviewed the cross-border advisory arrangement for Brazilian regulatory and tax compliance?",
    "What is the intended contract start date, and should payments be made on the 1st of each month or upon invoice?",
    "Are there equity or option grant components to this advisory arrangement in addition to the cash retainer?",
    "Did the bank account details arrive via a new or unusual communication channel (e.g., personal email, WhatsApp) rather than a verified Helix system? This affects fraud-risk triage priority."
  ],
  "risks": [
    "HIGH \u2014 Business Email Compromise (BEC) / fraud risk: Unsolicited new bank account details accompanying a new vendor setup is a classic BEC vector; payment must not be initiated until bank details are independently verified through a trusted, pre-existing contact channel",
    "HIGH \u2014 No playbook or policy baseline exists (empty playbook): all decisions are being made without confirmed Helix-specific policies, meaning errors in tax, legal, or process compliance are more likely",
    "MEDIUM \u2014 Brazilian cross-border payment compliance: Brazil has strict currency control and tax withholding rules (Receita Federal); non-compliance could expose Helix to penalties or payment failures",
    "MEDIUM \u2014 Missing signed agreement: initiating payment without an executed SAA creates IP ownership ambiguity and no enforceable payment terms",
    "MEDIUM \u2014 Tax withholding exposure: without a W-8BEN or equivalent, Helix may have US withholding obligations on payments to a foreign person; failure to withhold could create IRS liability",
    "LOW-MEDIUM \u2014 Advisor conflict of interest: no mention of COI disclosure or IP assignment, which are standard protections in biotech advisor agreements",
    "LOW \u2014 FX and transfer cost risk: $3,000/month in cross-border payments may incur significant fees or exchange-rate losses without the right payment platform"
  ]
}

  Coverage of Helix reference: 69% (9/13 items)

────────────────────────────────────────────────────────────────────────
RUN 2: WARM  (self-built Helix playbook + skill routing)
────────────────────────────────────────────────────────────────────────

  Router picked 5 of 6 skill sections:
    ✓ Banking & Payments
    ✓ Approvals & Routing
    ✓ Vendor & Customer History
    ✓ Contract Templates
    ✓ Compliance
    · Equity & Cap Table
  Context: 4145 chars → 3686 chars  (11% reduction)

{
  "actions": [
    "Use scientific advisor agreement template v1.4 (NOT the domestic MSA v3.2 or international IC template v2.1) \u2014 this is a scientific advisor engagement requiring the IP assignment clause Marcus added after the 2024 patent dispute",
    "Add the non-compete disclosure requirement to the agreement covering conflicting advisor positions at other biotechs, as required for all Helix advisor agreements",
    "Determine whether Dr. Costa will access confidential research \u2014 if yes, prepare a separate IP/confidentiality addendum in addition to the base advisor template v1.4",
    "Conduct a 1099-vs-W-2 (or equivalent independent contractor) classification assessment for Dr. Costa before engagement begins, per the policy established after the 2023 worker misclassification issue \u2014 document the basis for his classification given he is Brazil-based",
    "Have the relevant tech lead (Priya, for engineering/scientific roles) review Dr. Costa's background before the advisor agreement is signed",
    "Obtain VP-level or above signatory from Helix side before executing the MSA/advisor agreement; confirm Dr. Costa does not need to provide a matching-level signatory (he is an individual advisor, but note the MSA signatory rule applies to customer-side contracts \u2014 flag internally if there is any ambiguity)",
    "DO NOT use the bank account details Dr. Costa provided in his message \u2014 per Helix policy, any vendor/payee bank account change request must be voice-verified with the known contact on file using previously verified contact details only",
    "Contact Dr. Costa via previously verified contact details (on file before this request) to voice-verify the new Brazil bank account information before recording or using it for payment",
    "Once bank details are verified, route all payments to Dr. Costa through Wise (not Mercury ACH) \u2014 he is an international payee based in Brazil, and Helix routes all international payments through Wise per Q2 2024 policy",
    "Confirm whether $3,000/month triggers the $5,000 single-payment threshold \u2014 monthly payments of $3,000 do not individually exceed $5,000, so CEO (Marcus) approval is not required per payment; however, confirm if the total contract value ($36,000 over 12 months) triggers any aggregate approval requirement and escalate to Marcus if Helix policy covers total contract value",
    "Collect a W-8BEN-E form from Dr. Costa (as applicable for a Brazilian entity or individual) prior to first payment, consistent with international contractor tax documentation requirements",
    "Confirm Dr. Costa's billing/payment country is Brazil and assess any nexus or sales tax implications \u2014 Helix collects sales tax only in California and New York, so this engagement should not trigger collection obligations, but document the confirmation"
  ],
  "questions": [
    "Does Dr. Costa have previously verified contact details already on file at Helix so we can perform the required voice verification of his new bank account? If not, how was he engaged prior to this request, and who can confirm a trusted out-of-band contact method?",
    "Will Dr. Costa have access to confidential Helix research? This determines whether the separate IP/confidentiality addendum is required in addition to advisor template v1.4",
    "Has a prior advisor agreement or engagement existed with Dr. Costa, or is this a new relationship? This affects whether there are any existing bank details on file to compare against",
    "Is the worker classification assessment already completed for Dr. Costa, or does it need to be initiated now? Who will own that assessment given he is Brazil-based?",
    "Does Helix's $5,000 approval threshold apply per-payment or to total contract value? If it covers aggregate contract value, the $36,000 total would require Marcus's approval before signing"
  ],
  "risks": [
    "FRAUD RISK: Dr. Costa's new bank account details were submitted as part of the inbound request \u2014 Helix policy strictly prohibits using contact information or account details provided within a change request for verification; using these details without independent voice verification creates serious payment fraud and social engineering exposure",
    "IP RISK: Using the wrong agreement template (e.g., domestic MSA v3.2 or international IC v2.1 instead of advisor-specific v1.4) would omit the critical IP assignment clause, replicating the exact scenario that led to the 2024 patent dispute",
    "MISCLASSIFICATION RISK: Skipping the 1099-vs-W-2 (or international equivalent) classification assessment before engagement exposes Helix to worker misclassification liability, which was a documented 2023 compliance issue",
    "PAYMENT ROUTING RISK: Routing Dr. Costa's payments through Mercury ACH instead of Wise would violate Helix's international payment policy and may result in failed or non-compliant transactions",
    "MISSING ADDENDUM RISK: If Dr. Costa will access confidential research and the IP/confidentiality addendum is omitted, Helix's proprietary research could be inadequately protected",
    "MISSING NON-COMPETE DISCLOSURE RISK: Failing to include the non-compete disclosure requirement in the advisor agreement leaves Helix exposed to undisclosed conflicts of interest from Dr. Costa advising competing biotechs"
  ]
}

  Coverage of Helix reference: 92% (12/13 items)

========================================================================
QUANTIFIED IMPROVEMENT (held-out cross-task case, same model)
========================================================================
  Cold  :    69%  (general LLM knowledge only)
  Warm  :    92%  (general + accumulated Helix-specific facts)
  Δ     :   +23 percentage points  (from learning across 5 cross-domain tasks)

  What the warm plan still misses:
    • [action] Apply the standard advisor equity grant — 0.05% vesting over 12 months (from T4) — but flag for Marcus since Helix has no precedent for international advisor equity

Saved final playbook to Iter5-memory.md (per-episode snapshots in Iter5-memory_ep1.md … Iter5-memory_ep5.md)
(base) sarinafernandez-grinshpun@ist-11610 compoundingAgent % 
```

#### Continuations: 
- Tiered memory: legacy or outdated information gets cut or vectorized and stored
- Sleep-time compute, this could work well since for each of the typical tool calls they can pre customize the plan with the specific preerences or rules of the company
- The current retrieval process is cutting valuable information. Maybe actually check bullet by bullet but use a more rudimentary model.
- Different playbooks for different roles.
- Having the playbooks auto added to skill libraries (automatic primitive synthesis)
