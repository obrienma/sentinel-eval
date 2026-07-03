# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Standalone AI evaluation framework scoring outputs of Sentinel-L7
(`ComplianceDriver`) and Synapse-L4 (`Axiom` pipeline). No Sentinel/Synapse
-specific code lives in the harness itself — see
`docs/adr/0001-standalone-module.md`.

```bash
uv sync          # install dependencies
uv run pytest    # run the test suite
```

## Journaling

At the end of any development phase, before proposing a commit or when the
user requests a commit message, follow the journal-anki skill at
`~/.claude/skills/journal-anki.md` to write a journal entry
(`docs/journal/`) and paired probe cards (`docs/probes/`). Do not use
`LEARNING_LOG.md` — this repo never adopted it; journal-anki is the only
logging convention here.
