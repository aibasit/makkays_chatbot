# RAG Filter Extraction

Read the user's latest message and return a JSON object of search filters to narrow
the product/document search, using only fields you have real evidence for:

- `category` — product category or type mentioned (e.g. "switch", "access point", "UPS").
- `budget_max` — a maximum budget, if stated.
- `quantity` — a unit count, if stated.
- `keywords` — a short list of other distinguishing terms from the message (brand,
  port count, PoE, rack size, etc.).

Return `null` for any field without clear evidence in the message. Do not infer a
category or budget the user did not actually mention.
