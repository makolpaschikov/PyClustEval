---
name: experiment-design
description: Design a PyClustEval experiment series when the research topic is known and the comparisons still need to be chosen or justified. Work with the researcher on questions, controls and feasible scope, then save the agreed design in Markdown for the campaign operator.
---

# Experiment design

## Choose the research question

Start from the researcher's wording and any supplied manuscript excerpt, prior results or constraints. For a broad topic, offer a few plausible questions and show the comparison each would require. For example, "Which methods retain quality as client data become more heterogeneous?" calls for a different design from "How much time does each method need to reach a given quality?" Ask which conclusion matters most, or invite the researcher to suggest their own. Build on decisions already made.

Use [experiment-campaign](../experiment-campaign/SKILL.md) when the researcher already knows what to compare and wants to refine or run it. An outline in chat is enough. Stay with design when the question is whether a proposed comparison would support the intended claim.

## Design comparisons that support the intended conclusions

- For each question, propose a comparison with a recognizable name. Identify the reference condition, what varies, what is held constant, what will be measured and how the observations bear on the question. Flag when two factors vary together and narrow the claim or propose a comparison that separates them.
- Resolve choices that change interpretation with the researcher. These may include the data and methods, factor levels, meaning of performance, measurement conditions, which source of variation the repeats sample, and how results will be compared across repeats. Explain consequential choices in the context of the claim. Leave executable settings to the operator when they can be chosen without changing that claim.
- Consult primary sources independently when a specific methodological decision could change the design. Explain which decision the source informs and retain its citation with the rationale. If evidence is inconclusive, make the uncertainty visible. Agree separately on any broader literature review.
- Check feasibility against the project's [plan format](../../../docs/CAMPAIGN_PLANS.md), relevant inputs and [backend profiles](../../../docs/CAMPAIGN_PROFILE.md). Inspect the implementation when those sources leave a material capability unclear. Distinguish documented support, local availability and an unverified prerequisite. If a valuable comparison requires an extension, offer it once, explain the gain and any feasible alternative's limits, and follow the researcher's choice. Application changes and experiment launches require their own authorization.
- If the series exceeds the available budget, protect the highest-priority question. Show the smallest set of comparisons that can still answer it and what each optional addition buys. For example, a new partition samples variability within a dataset, while a second dataset tests whether the observation carries over. Where no affordable subset supports the desired conclusion, explain what narrower question is feasible. Use counts or comparable measurements to describe cost and let the researcher choose the tradeoff.

## Hand the agreed design to the operator

Review the proposed comparisons, limits and outstanding decisions with the researcher. Once agreed, save a standalone Markdown file in the researcher's language at the requested or an appropriate in-scope project location. Return its path so a new chat can use it directly.

State the research goal and scope. Give each agreed comparison one named table row with its question, reference condition, varying and fixed conditions, measures and the conclusion the design can support. Put shared conditions and longer rationales around the table, including source links where they informed a choice. Record budget choices and open questions for the operator. Carry over known dataset, method and protocol references. If an alias or fixed setting depends on another conversation, include its lookup location when available or flag what the operator must recover. Separate any expressly deferred scenarios from the agreed rows. If an open choice could change a conclusion, identify what still needs the researcher's decision before that comparison can proceed.

The operator can translate the named rows into runner settings, validate the executable plan and seek any required launch decision. Delivering the design ends this task.
