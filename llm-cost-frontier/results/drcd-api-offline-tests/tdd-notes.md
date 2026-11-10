# Offline TDD evidence (no live API)

Observed RED → GREEN cycles in this implementation session:

1. Initial ledger test: `native persistent budget ledger missing` (1 failing test); native ledger cell added → 1 passed.
2. Reserve-before-send / exact counter tests: 3 failures (`paid_request` / `input_count` missing) → 5 passed after native wrappers.
3. Manifest / scoring / dev-USD / replay: 4 missing-feature failures → 9 passed after native protocol cells.
4. Explicit fresh authorization / response redaction: 2 missing-feature failures → 13 passed.
5. Independent API watchdog / IPC runner: 3 missing-feature failures → real request-deadline worker+child kill and real IPC replay/write-failure cleanup passed.
6. Shared 90-attempt cap / successful-final-cell callback: 2 assertion failures → both passed after cap and post_run_cell fixes.
7. Final request ambiguous after 90 rows: replay incorrectly called it complete; parser regression failed (`complete != partial`) → green after requiring all 90 costs resolved.

Final full transcript is `unittest.log`: 44/44 passed, original 21 + new API 23, no skips.
`replay-execution.json` records the real owned IPC kernel execution. `verification.json` checks source/output cells, manifest SHA, and unchanged original tracked CPU/raw files.

These tests use temporary ledger / response parsing / routing fixtures only. They did not run a credentialless fake fresh, read a real key, or contact token-counting/inference APIs. No fixture is saved under the experiment's `results/drcd-api/`; that directory remains absent. Replay reports `not_run`, never synthetic API scores or savings.
