# Task 32 — Skip jobs from blacklisted companies

**Status:** 🟡 In progress

**Goal:** Let the user list companies they don't want to apply to. AutoJobApply
skips every LinkedIn posting from those companies and continues to the next
eligible job.

**Configuration**

- Create `blacklist company/companies.json` at the project root. It holds a JSON
  list of company names, each as displayed on LinkedIn, for example
  `["Acme", "Globex Corp"]`. Blank names are ignored.
- Match the entire company name, ignoring case and leading, trailing, or repeated
  whitespace. `Acme` matches ` ACME ` but does not match `Acme Labs`. List name
  variants as separate entries if they should all be skipped.
- Load the list once per run. An empty list (`[]`), an empty file, or a missing
  file leaves job selection unchanged. If the file exists but cannot be read, is
  not valid JSON, or is not a list of names, report the file error and stop
  before processing jobs.

**Implementation slices**

1. Add the editable file and a small module that loads and matches company names.
   Document where to edit the list and verify exact matching and empty-list behavior.
2. Apply the check in the shared LinkedIn results scanner
   (`src/tools/linkedin_job_selection.py`) so it covers the first job, subsequent
   jobs, pagination, and date-range fallback. Use the company shown on the job
   card when available; otherwise check the confirmed job details pane before
   continuing. A blacklist match must skip before resume matching or clicking
   **Easy Apply**, in either submission mode.
3. Report the skipped company and job title in the run log and browser status.
   Treat the match as a normal filter: keep scanning, don't count it as an
   application, and finish cleanly when no eligible jobs remain, including when
   every result is blacklisted. Verify both the initial scan and the repeat loop.

**Acceptance criteria**

- Adding a company to `blacklist company/companies.json` skips all of its postings
  on the next run, even if they have different job titles or appear on different
  results pages. Removing the company makes its postings eligible again.
- An unlisted company with a similar name remains eligible, even if it has a
  posting with the same title as a skipped job.
- A blacklisted posting never reaches the resume matcher or opens Easy Apply.
- In a live LinkedIn browser check, confirm that a listed company is skipped and
  that the next eligible posting is selected. Also verify that an all-blacklisted
  result set ends cleanly. Stop before submitting an application.
