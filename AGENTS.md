# Repository instructions

## Division of work

- Codex owns code: the eval suite, fixtures, scorer, CI, and this file.
- Use one issue per PR. Never push to `main`.
- Claude Code reviews every PR and owns the narrative sections of `FINDINGS.md`.
- Codex fills the finding tables. Claude Code will use the same cases for the competitor review.
- The owner decides which findings need generator fixes. The owner does all outreach.
- Agents never send messages, applications, or forms to other people.

## The one rule that matters

Week one is tests and findings, not fixes. A failed constraint case records a finding.
Do not change generator behavior to make a case pass.
Mark each confirmed failure with `pytest.mark.xfail(strict=True)` and its finding ID in the reason.
A future fix must cause a hard XPASS until the case loses its finding marker.
Use separate PRs with the `fix` label for generator fixes, after the owner decides.

Record constraint violations only. Do not record training opinions.
A barbell exercise violates a stated no-barbell constraint.
A preference for fewer sets does not define a constraint.
Exclude cases that depend on training philosophy.

## Work rules

- Run `pytest -q` before every commit.
- Target `main` in every PR. Never push to `main`.
- Use branch names `eval/<topic>` or `fix/<topic>`.
- Use one issue per PR.
- Use Simplified Technical English in docs and PR text.
- Refer to the owner as "the owner" in all text.
- Use Python 3.11, pytest, and standard library JSON tools.
- Add no runtime dependency without an issue that states the need.
- Pass `history=[]` or a synthetic fixture in every eval call. Never read the owner's history file.
- Use synthetic athletes only. Never use real names.
- Keep each PR body below 200 words. State additions, case counts, findings, and run commands.
- Keep the eval corpus, raw outputs, scores, and finding references together.

## Delivery

The owner authorizes merges of eval PRs after Claude Code review and a CI pass.
This permission does not include generator fixes.
Create the next branch from current `main` after each merge.
