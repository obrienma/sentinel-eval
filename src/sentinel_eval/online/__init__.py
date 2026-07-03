"""Online (unlabeled traffic) scoring layers, cost-ordered.

1. heuristics    — free, deterministic, always available.
2. disagreement  — cross-provider/cross-temperature comparison.
3. consistency   — embedding-based nearest-neighbor agreement.
4. judge         — LLM-as-judge, best-effort, reserved for the ambiguous
                    tail flagged by layers 1-3.

See docs/adr/0001-standalone-module.md for the full design rationale.
"""
