# Company blacklist (Task 32)

Edit `companies.json` in this folder to list companies AutoJobApply must never
apply to. It is a JSON list of company names, each written exactly as LinkedIn
displays it:

```json
["Acme", "Globex Corp", "Initech Pty Ltd"]
```

- Matching is on the **entire** name, ignoring case and extra whitespace:
  `Acme` skips ` ACME ` but **not** `Acme Labs`. Add each variant as its own entry.
- Blank names are ignored. The list is read once when a run starts; edit it
  between runs.
- An empty list (`[]`), an empty file, or a missing file skips nothing. A file
  that exists but cannot be read, is not valid JSON, or is not a list of names
  stops the run before any job is processed.
