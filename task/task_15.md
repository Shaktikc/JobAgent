# Task 15 — Auto-describe resumes in the new-resumes folder, then move them into resumes/ (Task 3.2)

**Status:** ✅ Done

**Goal:** Add a dedicated intake folder for newly added resumes — by default
`resumes/new/` — and run **Subtask 3.2** on every supported resume placed there.
The LLM writes the resume's short profile, the profile is stored in
`data/resume_descriptions.json` keyed by the resume's canonical path (plus the
file's mtime/size), and **after the mapping is stored** the resume is moved into
the existing `resumes/` folder. The file then becomes a normal pool resume with
the same description, ready for the Task 3 LLM to choose and Task 4 to attach.

Every new resume therefore gets a description mapping before it joins the main
pool, and the intake folder is emptied after successful processing. A resume is
never overwritten, and its **contents** are never modified; moving is a rename,
not an edit. The LLM is the only description and matching path — there is no
deterministic fallback.

## Preconditions
- Task 3 and Subtask 3.2 are complete: `ensure_descriptions` produces and stores
  LLM descriptions, and the match uses those descriptions.
- The main resume pool (`resumes/`) still works exactly as today and is writable.
- An LLM is configured (`OPENROUTER_API_KEY` + `AUTOJOB_LLM_MODEL`) for describing
  resumes. Without it, Task 3.2 records an error and stops; it does not fabricate
  a description or move the file.
- Supported resume formats are `.pdf`, `.docx`, `.txt`, and `.md`
  (`RESUME_SUFFIXES`).
- The new-resumes folder may not exist yet; it is created on demand.
- The intake folder and the main pool are different directories. If they resolve
  to the same folder, processing stays in place and no move is attempted.

## Inputs
- `resumes/new/` — the new-resume intake folder. Configurable with
  `AUTOJOB_NEW_RESUMES_DIR`; when unset it defaults to `<resumes_dir>/new`.
- The existing resume pool `resumes/` — the destination after a resume is
  described.
- The resume-description store `data/resume_descriptions.json` (configurable
  with `AUTOJOB_RESUME_DESCRIPTIONS`).
- The remembered-resume library `data/resume_library.json` (Task 3.1), in case
  an entry points at a resume being moved.
- The LLM client from `LLMSettings` (same model, temperature, JSON mode, and
  hidden-reasoning setting as Subtask 3.2).

## Implementation order (bottom-up, easy to test)
1. **Settings and folders** — add the intake-folder setting and default.
2. **Discovery** — find supported resumes in the intake folder.
3. **Description mapping** — run Task 3.2 on each intake resume in place.
4. **Move after mapping** — move the described file into `resumes/` without
   overwriting anything, and move its description entry to the new path.
5. **Explicit describe-and-move command** — process the intake folder without
   opening a browser.
6. **Matching integration** — the moved resume is a normal main-pool candidate
   and its path is handed to Task 4.
7. **Tests and live verification** — unit tests first, then a real LLM/browser
   check.

## Steps
1. **Add the intake folder setting.**
   - Add `new_resumes_dir` to `Settings`, with a property/default of
     `self.resumes_dir / "new"` when no explicit path is configured.
   - Read `AUTOJOB_NEW_RESUMES_DIR` in `load_settings`; expand `~` and keep the
     existing `AUTOJOB_RESUMES_DIR` behavior unchanged.
   - Create the folder on demand when Task 3.2 first needs it. Do not create a
     placeholder resume or any other file inside it. Document the default in
     `.env.example` and `README.md`.

2. **Discover resumes in the intake folder.**
   - Keep `list_resume_files(resumes_dir)` as the single-folder helper.
   - Add a small intake helper that returns the supported **direct children** of
     the intake folder, sorted by name. Do not recurse into arbitrary
     subfolders.
   - Ignore unsupported files and non-file entries in the intake folder.
   - The main pool keeps using its existing discovery path, so resumes already
     in `resumes/` behave exactly as today.

3. **Describe each intake resume before moving it.**
   - Run `ensure_descriptions` over the intake files (using Task 3.2's normal
     store and LLM path) before touching the main pool.
   - For each file:
     - reuse an entry whose recorded mtime/size still match, with **no** LLM
       call and no text extraction;
     - extract the readable text and ask the LLM for the structured profile
       when the file is new or changed;
     - store the profile under the file's canonical intake path together with
       its current mtime and size;
     - update the existing entry for the same path instead of adding a
       duplicate when the file is re-described.
   - If the LLM is unconfigured, the file has no readable text, or the call
     fails/returns an unusable reply, record the error and stop processing that
     file. Do not write a fake or deterministic description, do not move the
     file, and do not match it from raw text. Existing mappings for other files
     remain untouched.

4. **Move the described resume into `resumes/`.**
   - Only a resume whose description was successfully stored is eligible to
     move. The move happens **after** the mapping exists, never before.
   - Move the file into the main `resumes/` folder, preserving its file name.
   - **Never overwrite an existing file.** If a file with that name already
     exists in `resumes/`, choose the next free name in the same style as
     `store_uploaded_resume`: `stem (1).suffix`, `stem (2).suffix`, and so on.
   - Use a real move/rename (`shutil.move` or `Path.replace` with the
     collision-safe destination), not copy-and-delete unless that is required
     by the platform. Do not alter the file's bytes.
   - After the move, re-stat the file and rewrite the description store so the
     profile moves from the old canonical key to the new canonical key:
     - remove the old intake-path entry;
     - add/update the entry for the new main-pool path with the same profile
       and the file's current mtime/size;
     - leave exactly one entry for the resume and never create a duplicate.
   - If any remembered-resume library entry (`data/resume_library.json`) points
     at the old intake path, update it to the new path so similar-job reuse keeps
     working. Do not add new library entries that were not there before.
   - If the move fails (permissions, lock, cross-device issue):
     - record a clear error;
     - leave the resume in the intake folder;
     - keep its description mapped under the intake path (the file still
       exists and is still described);
     - never delete the file and never overwrite the destination;
     - stop the current describe/match operation rather than silently
       continuing with a half-processed intake folder.
   - Never move a file unless its description was stored successfully.

5. **Add an explicit "describe and move new resumes" command.**
   - Add a CLI flag (for example `uv run autojob --describe-new-resumes`) that
     runs the same Task 3.2 description path over the intake folder and then
     moves each successfully described file into `resumes/`, **without**
     launching the browser or opening a job.
   - Print a short per-file result: `described`, `reused` (fresh description),
     `moved`, `failed`, plus a final summary, the intake path, and the store
     path. Show the final main-pool path for each moved file.
   - Exit `0` only when every supported file in the intake folder was
     successfully described and moved; exit non-zero with the real error when
     the LLM is unconfigured, the file is unreadable, the call fails, or the
     move fails.
   - The command must not create, overwrite, or modify the contents of any
     resume file.

6. **Make normal matching process the intake folder first.**
   - At the start of Task 3's resume preparation, process the intake folder:
     describe each supported resume, then move each successfully described file
     into the main pool. Only after that should the normal main-pool description
     and match run.
   - If intake processing fails, record the Task 3.2 error and stop the match
     cleanly. Do not silently skip the file, match from raw text, or ask the
     human for a replacement.
   - After successful processing, build the candidate list from the main
     `resumes/` pool as usual, so moved resumes are considered by the LLM.
   - A resume without a stored description remains an error, not a candidate
     read from raw text.
   - The LLM may select a previously moved intake resume; record its new path
     and rationale exactly as for any main-pool resume, and hand that same path
     to Task 4 so it can be attached/uploaded.
   - If the intake folder and main pool are the same directory, describe files
     in place and skip the move; record that no move was needed.

7. **Keep the errors clean and auditable.**
   - Record the intake-folder path and counts for found/described/moved/failed
     resumes in the Task 3 outcome and log.
   - A failed description or move is a clear Task 3.2 error, not a silent
     fall-through to "no match", a human upload prompt, or a half-mapped resume.
   - Never write resume text, prompts, or credentials to the description store;
     it contains only the profile, mtime, and size.

8. **Update the documentation.**
   - `README.md`: explain that new resumes can be dropped into `resumes/new/`;
     Task 3.2 describes them automatically on the next match (or with the
     explicit command), then moves them into `resumes/` without overwriting
     anything.
   - `.env.example`: document `AUTOJOB_NEW_RESUMES_DIR` next to
     `AUTOJOB_RESUMES_DIR`, including its default and supported formats.
   - Update the layout section to show `resumes/new/` and the CLI flag.
   - Do not claim that a background file watcher exists.

9. **Tests.**
   - Unit tests:
     - the intake folder defaults to `<resumes_dir>/new` and an env override is
       honored;
     - intake discovery includes supported files, ignores unsupported files,
       and only reads direct children;
     - a new intake resume gets exactly one LLM description entry keyed by its
       **intake** path before the move;
     - after a successful move, the file is in the main folder, the intake
       folder no longer contains it, and the store has exactly one entry keyed
       by its **new main-pool** path (old key removed);
     - an unchanged intake resume is reused with no additional LLM call before
       being moved;
     - a changed intake resume is re-described, moved, and its entry is updated,
       not duplicated;
     - a name collision does not overwrite the existing main-pool file and uses
       a collision-safe name;
     - a failed description leaves the file in the intake folder with no fake
       mapping and surfaces the error;
     - a failed move leaves the file in the intake folder, keeps its intake-path
       mapping, does not overwrite the destination, and surfaces the error;
     - a remembered-resume entry pointing at the intake path is updated to the
       new path after the move;
     - the explicit command reports `described`/`reused`/`moved`/`failed` and
       returns the correct exit code without launching a browser;
     - matching processes the intake folder, then passes the moved main-pool
       resume to Task 4 as the selected path;
     - the existing main-folder tests and behavior stay unchanged.
   - Integration/live check (required):
     - Put a real supported resume in a temporary `resumes/new/` folder with a
       configured LLM, run the explicit command, and confirm the description
       mapping exists under the file's canonical main-pool path, the file is in
       `resumes/`, and the intake file is gone.
     - Run the real Task 3 resume-selection check (for example
       `AUTOJOB_RESUME_LIVE=1 uv run pytest tests/integration/test_resume_selection.py -s`)
       with that file having come from the intake folder and confirm it is
       considered, can be selected, and the selected path is the one Task 4
       would attach.
     - Confirm the move did not overwrite an existing resume and did not change
       the file's bytes (compare size/hash before and after).
     - Never click **Submit application** during verification.
   - If implementation exposes a new bug, add the matching
     `known Bugs/task_15_bugs.md` and a row in `known Bugs/bug_log.md` with the
     symptom, root cause, fix, status, and evidence.

## Acceptance criteria
- A supported resume placed in `resumes/new/` is described by Task 3.2 and gets
  a mapping in `data/resume_descriptions.json`.
- **After** that mapping is stored, the resume is moved into `resumes/`; the
  intake folder no longer contains it, and the file's contents are unchanged.
- The mapping is rewritten to the resume's new canonical path: the old
  intake-path entry is removed, exactly one entry remains, and it records the
  file's current mtime/size.
- A name collision never overwrites an existing resume; the moved file gets a
  collision-safe name.
- Fresh mappings are reused without re-extracting or re-summarising the resume;
  a changed file is re-described; the same path always has one entry.
- The store contains the profile plus mtime/size only — no resume text, prompts,
  or credentials.
- A resume moved from the intake folder is a normal main-pool candidate: the
  LLM can select it and the selected path is handed to Task 4.
- A resume without a description is still an error, never matched from raw text.
- An unconfigured LLM, unreadable file, failed call, unusable reply, or failed
  move produces a clear error and no data loss:
  - no deterministic/fabricated mapping;
  - the file stays in the intake folder if it was not moved;
  - an existing destination is never overwritten;
  - the describe command exits non-zero and the normal match stops cleanly.
- Existing `resumes/` behavior, human-upload storage, and remembered-resume
  reuse remain unchanged.
- Unit tests and the live LLM/browser checks pass. The task is not marked done
  from unit tests alone.
- No application is submitted by this task.

## Notes
- **What "new resume folder" means:** by default `resumes/new/`, directly under
  the main pool. It can be pointed elsewhere with `AUTOJOB_NEW_RESUMES_DIR`, but
  it is still the intake folder for the main pool. Do not confuse it with the
  main `resumes/` folder or the `data/` state directory.
- **Promotion after mapping:** the only file operation this task adds is the
  move from the intake folder to `resumes/` after a successful description. The
  move is a rename; the resume's bytes are never edited. The task never deletes
  a resume.
- **Mapping key follows the file:** because the description store is keyed by
  canonical path, moving the file must also move its entry. A stale intake-path
  key or a duplicate main-path key is a bug.
- **Trigger semantics:** placing a file does not spawn a background daemon. The
  description-and-move step runs (a) when Task 3 prepares to match a job, which
  is the normal automatic path, or (b) immediately when the user runs the
  explicit describe command. A polling file watcher is out of scope.
- **Failure leaves the work recoverable:** a failed description or move keeps
  the file in the intake folder so a later run can retry. Never delete it and
  never overwrite an existing `resumes/` file to force progress.
- **Cost:** a new or changed file costs one LLM describe call; an unchanged file
  costs none. The existing bounded concurrency in `ensure_descriptions` applies.
- **Do not break Task 3.1:** human-uploaded resumes still go directly into the
  main `resumes/` folder and are described there; the intake folder is for
  resumes the user adds manually.
- **Interrelated updates:** configuration, resume discovery, the description
  store's key rewrite, the remembered-resume library path rewrite,
  `ensure_descriptions` callers, matching/selection, the CLI summary/command,
  README, `.env.example`, and every affected unit/integration test must change
  together.
- **Task-file rule:** do not edit `task/` files during implementation except to
  mark this task in progress/done and update `task/task.md`.
- Never click **Submit application**; submission remains a manual human step.
