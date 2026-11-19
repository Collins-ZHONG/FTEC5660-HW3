---
name: ftec5660-hw3
description: Help complete and report on FTEC5660 Homework 3, the Fisher 15-point investment agent assignment, using the provided repository and rubric.
metadata:
  short-description: FTEC5660 HW3 workflow
---

# FTEC5660 Homework 3

Use this skill when the user asks to understand, implement, test, or report on FTEC5660 Homework 3 in the `FTEC5660-HW3` repository.

## Start by inspecting

- Read `Homework 3(1).pdf` and repository `README.md` for the current assignment and report requirements.
- Inspect `hw3.py`, `requirements.txt`, `.gitignore`, and current Git changes before editing. Preserve unrelated user changes.
- Treat the repository's actual paths and assignment files as authoritative. A generic work-directory skill may point to an older homework folder; do not switch workspaces when the user has opened this HW3 repository.

## Assignment requirements

- Select exactly three Fisher points (1-15) in `CHOSEN_POINTS`.
- Implement only the marked student sections in `hw3.py`: `CHOSEN_POINTS`, `build_agent()`, and `analyze_companies()`; do not alter provided tools, runner, or scoring code unless the user specifically asks.
- Use LangChain with the required `deepseek-v4-flash` model. Never hard-code or commit API keys; the `.env` file must remain private and untracked.
- For each company, return PASS/FAIL for each selected point and a short evidence-based summary. Catch failures per company so one API error does not prevent a results file.
- Access company evidence only through the four provided tools: `list_documents`, `read_document`, `sql_query`, and `interview`. Do not read `company.db` or `interviews.dat` directly in agent logic, and do not use web search or outside company sources.
- Respect the maximum of 10 interviews per company. Choose a role that knows the selected topic, as specified in the README/PDF.
- Compute sums, ratios, and date differences in SQL or Python, not in the language model's mental arithmetic. Use aggregates because SQL tool results are capped at 50 rows. Cross-check management statements against database or interview evidence where relevant.

## Implementation and testing workflow

1. Map each selected point to its prescribed evidence source and define a clear PASS/FAIL rule before implementing prompts or routing.
2. Use the public `ground_truth.json` to compare candidate point rules on all 20 public companies. It contains labels for all 15 points; do not hard-code answers, company names, or folder names in the solution.
3. Build a bounded, reliable LangChain workflow. Route evidence gathering to the right tools, keep interview use within budget, require machine-readable verdicts, and validate/normalize outputs before returning them.
4. Run `python hw3.py --data-folder public_test` in the configured environment. Confirm the process finishes, creates `results.csv`, and inspect the balanced score and per-company errors. Improve rules where public evidence indicates a mismatch.
5. Verify that no key is present in tracked files and that the solution can run end-to-end without relying on public answer labels at inference time.

## Report and submission

Update the `Homework 3 solution` section of `README.md` with:

- Why each of the three points was selected, its explicit PASS rule, and evidence used; quote Fisher where helpful.
- A design visualization (Mermaid is suitable) and one paragraph explaining how model calls and tools handle the points.
- The public-test point score, companies and points with disagreements, and evidence-based reasons for errors.
- The Task 2 reflection on AI sycophancy and AI psychosis. The assignment allows any format; follow the user's preferred format and do not invent their personal experiences or opinions.

The repository submission must include `hw3.py`, `requirements.txt`, and `README.md`, run from a fresh clone, produce `results.csv`, and remain public for grading. Do not publish, push, or change GitHub visibility unless the user explicitly requests that external action. The PDF states the deadline as November 16 at 23:59 HKT; verify the current course instructions if the user asks about deadlines.

## User collaboration

- If the user only asks what to do, explain the assignment and next steps without modifying their files.
- If they ask to implement or complete it, make the changes in the current HW3 workspace and verify them end to end.
- The user chooses the three points and owns the report/reflection content. If unspecified, propose a reasonable default, explain the tradeoff, and ask only when the choice materially changes implementation; continue any independent inspection meanwhile.
