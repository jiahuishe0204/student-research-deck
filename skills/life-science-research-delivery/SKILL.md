---
name: life-science-research-delivery
description: Produces evidence-grounded life-science research reviews and presentation content packs from a user-selected topic. Use when planning, researching, writing, verifying, or presenting a life-science, medical, pharmaceutical, or bioengineering topic.
---

# Life-Science Research Delivery

Turn a user-confirmed life-science topic into a traceable research report and a presentation-ready, slide-by-slide content pack. Work in Chinese by default; search concepts may be bilingual. This Skill defines the research method and tool-use policy. It does not contain credentials, grant database access, call the project's DeepSeek API, or operate the production website.

## Scope boundary

This Skill is for life-science research and evidence-grounded academic communication: biology, medicine, biotechnology, pharmaceuticals, bioengineering, and closely related translational topics. It is not a clinical decision tool, medical advice, systematic-review registration service, legal/patent opinion, or substitute for expert review. For patient-specific diagnosis or treatment requests, decline to make clinical decisions and redirect to a qualified clinician. For topics outside this scope, explain the boundary and ask whether the user wants a general, clearly labeled response instead.

## Research tools

Use tools available in the current agent session; do not assume that tools configured in another product, account, or project are available here.

- Use the agent's built-in web search for public scientific literature and official public sources. Prefer primary records and official endpoints; record the source, date, stable identifier/URL, and access level. Search results are discovery leads: open and check the underlying record before relying on it.
- Use the configured Patsnap/Zhihuiya patent MCP for patent records only when that MCP tool is actually exposed in this session. Search patents as a separate evidence stream. Label records as patents and use them for invention/activity/status context—not as proof of scientific efficacy, clinical safety, or peer-reviewed validation.
- Do not claim that this Skill invokes the project's DeepSeek API. The host agent's model runs the Skill unless a separately configured and explicitly requested API integration is used.
- Never ask the user to paste a secret into chat, browser search, a report, or an output artifact. Do not reveal credentials or include them in logs or deliverables.

## Tool failure and fallback

At the start of a live-research run, check whether web search and the patent MCP are available. If web search is unavailable, do not claim fresh public-source research; ask for source material or offer a clearly labeled planning draft. If patent MCP is unavailable or fails, continue with accessible scientific/public sources only when the requested scope permits, explicitly state that patent coverage was not performed, and do not imply otherwise. If either tool returns no usable results, report the actual query/access limitation and broaden or refine searches transparently; never fabricate results or silently substitute patents for papers. If a tool's availability, quota, or access is uncertain, state that uncertainty and ask before incurring paid usage.

## Required behavior

1. Respect the user's exact topic and intended audience. If the topic could support multiple materially different reviews, offer 2–4 distinct directions and wait for the user's choice. Never silently choose a direction.
2. Separate what is known from what is assumed, and separate plans from findings. Do not search or state research conclusions during intent clarification.
3. Use accessible, identifiable sources. Cite claims near the relevant text and keep a source ledger with DOI/PMID or stable URL, source type, access level (abstract/full text), and the claim/evidence it supports.
4. Never invent papers, identifiers, results, quotations, figures, or tool/API outcomes. A patent is not proof of scientific efficacy; an abstract is not full-text review; in-vitro or animal findings do not establish human benefit; association is not causation.
5. Keep the report and slides consistent. Preserve study population/model, intervention/material, comparator, conditions, effect direction, units, follow-up, and limitations. Distinguish evidence from interpretation.
6. Verify the important factual claims independently against the cited records. Mark each as supported, partly supported, unsupported, or not determinable; revise, remove, or clearly flag accordingly. If evidence is insufficient, say so rather than filling gaps with general knowledge.
7. Make a final readability and integrity pass: citations resolve, numbers and terminology agree, no unsupported certainty, no dangling references, no internal audit labels in audience-facing prose, and no slide that overstates its evidence.
8. Report tool and access limitations plainly. If no live search/API is available, ask for source material or produce a clearly labeled planning draft—not a purportedly researched final report. Do not expose credentials or send them to the browser.

## Workflow

Follow the nine-stage workflow in [references/workflow-and-quality.md](references/workflow-and-quality.md). Keep intermediate outputs and source/evidence identifiers so downstream writing can be traced and corrected. The research framework is topic-specific; do not force every topic into one fixed narrative template.

## Deliverables

Unless the user asks otherwise, provide:

- A Chinese research report: abstract, scope and method, topic-specific narrative, conclusion, limitations, and references.
- A slide-by-slide presentation content pack: slide purpose, title, concise on-slide content, evidence/source note, suggested visual (with exact source/figure locator when available, otherwise a concrete original diagram plan), and speakable speaker notes.
- A compact evidence/verification appendix listing unresolved claims and source-access limits.

Do not claim to create a PPTX unless a PPTX file was actually generated and checked. Figure links do not grant reuse permission; state the licensing status when unknown.

## Example

For a broad topic such as “conductive hydrogels in neural electrical stimulation,” first ask the user to select a focus (for example, chronic implant interfaces, neural injury repair, or wireless neuromodulation). Once the user selects “chronic implant interfaces,” scope the review around interface stability and evidence over time. Do not conclude that long-term clinical reliability is established merely from promising material studies or short-term animal results.
