# Agent memory (self-taught)

- • Always confirm the target system's field names, value formats (e.g., case, date order, units like cents vs. decimals), and schema before assuming standard conventions.
- • Always output customer names in ALL CAPS, dates in DDMMYYYY format, and use the exact field names specified by the target system's schema.
- • Use the exact JSON field names specified by the client/system (e.g., `"customer"` not `"customer_name"`), as renaming fields breaks downstream processing.
- • When representing monetary amounts, store them in cents as an integer under the key `amount_cents` (not `amount`) to make the unit explicit.
- • Output a JSON object with customer name in ALL CAPS, date in DDMMYYYY format, and amount converted to integer cents — never output null when the required data is present in the message.
