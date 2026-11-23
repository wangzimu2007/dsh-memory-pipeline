# Changelog

## v0.1.1 - 2026-11-23

### Fixed

- `pass` and `revise` admissions now require at least one evidence ID.
- VRAM waiting now uses the top-level global config instead of a tier's
  sub-config, so the configured threshold and timeout are actually applied.

### Tests

- Added a validator regression test for `pass` without evidence.
- All 6 unit tests pass.

## v0.1.0 - 2026-11-22

Initial public release.

### Added

- Tiered route Q4 → 9B → 27B → Strata → cloud.
- Deterministic validation for fact extraction and fact admission.
- Q4 self-repair attempt, then escalation on failure.
- Per-tier unloading after failure.
- Batch-end unloading of local models used by the run.
- VRAM-aware waiting with configurable timeout and poll interval.
- Direct start tier via `--start q4|9b|27b|strata|cloud`.
- Explicit-memory bridge in `remember_explicit.py`.
- Synthetic example cases and validator unit tests.
- Chinese and English README.

### Validation

- 6 validator unit tests pass.
- Local Q4 path passed 50/50 test cases.
- 9B failure path unloaded 9B, escalated to 27B, and cleaned up both.
- VRAM timeout path verified with an impossible threshold.

### Known limitations

- The cloud tier is an OpenAI-compatible adapter and needs an API key.
- A signed-in DSH account route cannot be used from an external process.
- Strata was skipped in the recorded test because the configured VRAM threshold was not met; it still needs a live run on a suitable machine.
- This repository contains the pipeline, not model weights or prompt contracts.
