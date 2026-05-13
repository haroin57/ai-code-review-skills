---
name: code-review-codex
description: Run a parallel multi-reviewer code review (Security / Performance / SRE / Coverage + Coordinator) on a diff using the OpenAI Codex CLI. Use when the user asks for a multi-perspective code review and wants the underlying model to be Codex/GPT rather than Claude.
---

# code-review-codex

Same shape as `code-review-claude`, but the backend is the OpenAI Codex CLI
(`codex exec`). Useful when the user wants a second opinion from a different
model family, or when API quota considerations favor Codex.

## When to invoke

- User explicitly asks for "Codex review" or "GPTでレビュー"
- User wants two independent passes (run both `code-review-claude` and this
  one, then diff the verdicts)
- Claude API is rate-limited / down

## Choosing the reviewer set

Use the same heuristics as `code-review-claude`. See that SKILL.md's
"Choosing the reviewer set" table for mapping user signals (徹底 → `--reviewers all`,
API契約 → `--force api-contract`, 依存 → `--force dependencies`, 設計 →
opt-in architecture, 読みやすさ → opt-in maintainability, 軽く → minimum
subset). The reviewer registry and flag semantics are identical between
backends. Always announce the chosen set before starting the run.

## Prerequisites

- `codex` CLI on PATH. Install via:
  ```bash
  npm install -g @openai/codex
  ```
- Codex must be authenticated (`codex login` or `OPENAI_API_KEY` set).
- Python 3.10+.

## How to run

Same flow as the Claude skill; just change `--backend`. **Always pass
`--output-dir` and run in the background** so per-reviewer XML and `run.log`
appear as work progresses — then tail the log via `BashOutput` or `tail -f`
to keep the user informed instead of staring at a blank terminal.

```bash
OUT=/tmp/review_out_codex_$(date +%s)
python3 "$SKILL_DIR/../../scripts/run_review.py" \
  --backend codex \
  --diff /tmp/review.diff \
  --language go --framework "net/http" \
  --environment production \
  --trust-boundary "untrusted HTTP" \
  --auth-method "session cookie" \
  --output-dir "$OUT"
echo "log: $OUT/run.log"
echo "summary: $OUT/summary.xml"
```

The runner pipes the rendered prompt to `codex exec -` (stdin mode) so large
diffs don't hit argv length limits.

Log format is identical to the Claude skill — see that SKILL.md for the
example output and progress-surfacing protocol.

## Options worth knowing

Identical to the Claude skill — see that SKILL.md for `--reviewers all`,
`--force`, `--skip`, `--dry-run`, `--no-coordinator`. The reviewer registry
(including conditional dispatch rules for `api-contract` and `dependencies`)
is shared between backends.

## Differences vs the Claude skill

| Aspect | Claude | Codex |
| --- | --- | --- |
| CLI | `claude -p` | `codex exec -` |
| Default model | per `~/.claude/settings.json` | per `~/.codex/config.toml` |
| Auth | Anthropic key / Claude Code login | OpenAI key / `codex login` |
| Output format | identical (XML, per prompt instructions) | identical |
| Reviewer registry | shared | shared |

## Cross-checking with the Claude skill

When confidence matters more than cost, run both skills with the same diff
and compare the `<verdict>` blocks. Disagreement is a signal — investigate
issues that only one side flagged. Agreement on `critical` is high-signal.

## Cost / safety notes

Identical to the Claude skill (5 invocations, prompt-injection-resistant
diff wrapping, human final sign-off).
