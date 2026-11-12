---
name: mutation-check
description: Run diff-scoped mutation testing to check that the tests for the current change can actually fail. Use for medium/high-risk changes or when coverage looks good but the tests may be weak.
argument-hint: "[base branch, default origin/main]"
---
Base branch: $ARGUMENTS (if empty, use origin/main).
Files changed against origin/main: !`git diff --name-only origin/main...HEAD`

Mutation testing changes the code in small ways ("mutants") and checks that some test fails. A surviving mutant in changed code means the tests don't pin that behaviour (guidelines TG-34).

1. Use `commands.mutation` from `.claude/testing-kit.json` if set. Otherwise pick by stack and scope to the changed source files only:
   - Python: `mutmut run --paths-to-mutate <files>` (mutmut 3: set `paths_to_mutate` in `[tool.mutmut]`), then `mutmut results`. Or the `mutmut-mcp` server if installed.
   - JS/TS: `npx stryker run --incremental --mutate <files>`
   - Rust: `cargo mutants --in-diff <(git diff origin/main...HEAD)`
   - Java: PIT with `-DtargetClasses=<changed classes>` (or the Gradle/Maven `scmMutationCoverage` goal)
   - Go: `go-mutesting <packages>`
   Tell the user if the tool isn't installed and give the install command; don't install it without asking.
2. Bound the run (time budget, changed files only).
3. Report: mutants generated / killed / survived / timed out, score, and each survivor in changed lines with file:line and the mutation.
4. For each survivor, either write a test that kills it (from the spec, not from the mutant) or explain why it's equivalent (no observable difference). Never delete or weaken code or tests to raise the score.
