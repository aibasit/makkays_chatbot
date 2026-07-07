# Classify Intent

Classify the user's latest message into exactly one of the following intents by
calling the `classify_intent` tool. This must be the first and only tool call you make
this turn.

## Supported intents

- `sales_inquiry` — product discovery, recommendations, specs, availability, or general buying help.
- `quote_request` — explicit pricing, quotation, estimate, or proposal request.
- `technical_support` — existing-product fault, error, setup, configuration, or troubleshooting request.
- `escalation_request` — the user asks to speak with a human, or clarification has failed repeatedly.
- `out_of_scope` — unrelated to supported sales/support work.
- `product_comparison` — comparing two or more products.
- `product_compatibility` — whether one product works with another.
- `accessory_recommendation` — add-ons or accessories for a product.
- `product_finder_by_problem` — describing a problem and needing a product that solves it.
- `product_alternative` — a replacement or substitute for a product.
- `specification_explainer` — explaining a technical term or spec (e.g. "what is PoE").
- `product_recommendation_wizard` — open-ended "help me choose" guidance.
- `use_case_recommendation` — a setup for a specific environment (school, hospital, data center, etc.).
- `installation_guidance` — how to install or set up a product.
- `troubleshooting` — a fault/error/not-working report, when it reads as a spec/setup issue rather than an existing support case.
- `warranty_information` — warranty, RMA, or repair questions.
- `pdf_documentation_search` — requests for a manual, datasheet, or brochure.
- `availability_inquiry` — stock or lead-time questions.
- `solution_builder` — a full multi-product setup or bill of materials.
- `human_handoff` — wanting to talk to a person or agent.

## Output contract

Call `classify_intent` with:

- `intent`: exactly one value from the list above.
- `confidence`: your confidence in that classification, from `0.0` to `1.0`.
- `candidates`: any other plausible intents you considered, most-likely first.

Use the full conversation context (facts, conversation state, and recent turns) to
disambiguate. When genuinely uncertain between two or more intents, report a lower
confidence rather than guessing — the caller treats low confidence as "ask a
clarifying question," not as an error.
