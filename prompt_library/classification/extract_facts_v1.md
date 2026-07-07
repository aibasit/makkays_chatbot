# Extract Facts

Read the user's latest message and the supplied conversation context, then return a
JSON object containing only the fields you were asked for in this turn's schema. Only
include a field if the message provides real evidence for it; otherwise return `null`
for that field. Never guess a company name, industry, product interest, or project
size — only extract what the user actually stated or clearly implied.

Do not extract contact email, phone, quantity, or budget here — those are handled by
deterministic extraction before this prompt is ever used. Focus only on qualitative
fields such as company, industry, product interest, and project size.
