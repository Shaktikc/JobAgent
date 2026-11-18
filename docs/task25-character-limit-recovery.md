# Character-limit recovery (Subtask 25.1)

After type conversion and grounded correction fail, rejected required free-text
answers can use a deterministic prefix within the discovered maximum length.
This is an explicit exception to the usual fact-preservation rule: trailing
wording may be dropped, but numeric tails and negated answers are refused.
The replacement control is checked before entry. The existing single navigation
retry applies. Audit records contain lengths and outcomes, never answer text.

Implementation verification is incomplete: focused unit tests pass, but live
LinkedIn and Chromium integration checks remain pending. Explicit helper-text
limit discovery and stricter replacement-constraint identity need completion.
