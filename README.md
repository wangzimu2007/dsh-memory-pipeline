# DSH Memory Pipeline

A tiered memory-processing pipeline for DeepSeek Harness (DSH): run a small local model first, validate the output, and escalate only when necessary.

Default route:

Q4 → 9B → 27B → Strata → cloud

The pipeline is designed for two memory jobs:

- **Fact extraction** — turn evidence segments into structured facts.
- **Fact admission** — decide whether a candidate fact should pass, be revised, dropped, or held.

It is not a complete memory database. It produces validated JSON; storing and retrieving memories is done by your memory backend.

## Why tiering

The small Q4 model is fast and cheap for most items. Larger models are only used when the small model's output fails strict validation.

Every tier must pass deterministic checks:

- valid JSON
- required fields
- evidence IDs exist
- valid fact type
- valid decision
- `revise` has a non-empty replacement
- `drop` / `hold` has no replacement

Q4 gets one repair attempt. If it still fails, the next tier is tried.

## Low-VRAM behavior

Local models are not kept resident after a batch.

- A failed Ollama tier is unloaded before the next tier starts.
- At the end of a run, Q4/9B/27B models used by this run are unloaded.
- Before loading a tier, available VRAM is checked.
- If VRAM is insufficient, the pipeline polls every 10 seconds and waits up to 30 minutes.
- It does not close games or other models. It only waits, then skips the tier if the timeout expires.

This makes it safe to start a batch while a game or another local model is running.

## Start from a specific tier

```bash
python memory_pipeline.py --cases examples/cases.example.json --start q4
python memory_pipeline.py --cases examples/cases.example.json --start 9b
python memory_pipeline.py --cases examples/cases.example.json --start 27b
python memory_pipeline.py --cases examples/cases.example.json --start strata
python memory_pipeline.py --cases examples/cases.example.json --start cloud
```

Tiers before the selected start tier are not run.

## Setup

1. Install Ollama and the desired models.
2. Download the memory-model prompt contracts and Modelfiles from:
   - https://github.com/lifdjgfndgn/qwen3.5-4b-memory-v2
   - https://huggingface.co/IMLIULIAN/qwen3.5-4b-memory-v2
3. Put that project under `vendor/qwen3.5-4b-memory-v2-main`, or change `prompts_dir` in the config.
4. Copy `pipeline.config.example.json` to `pipeline.config.json`.
5. Adjust model names and endpoints for your machine.

The prompt contracts are from the Qwen3.5-4B-Memory-V2 project, which is Apache-2.0. This repository only contains the pipeline; it does not redistribute model weights.

## Cloud tier

The cloud tier is an OpenAI-compatible adapter.

Set:

- `MEMORY_CLOUD_BASE_URL`
- `MEMORY_CLOUD_MODEL`
- `DEEPSEEK_API_KEY` or the key environment named in the config

If the key is missing, the cloud tier is marked skipped.

A DSH account route (for example `deepseek-account/deepseek-flash`) only works inside a signed-in DSH session. An external process cannot use it directly; use an API key, or integrate the pipeline as a DSH plugin.

## Explicit-memory bridge

`remember_explicit.py` is a small bridge for user-authorized memory ("remember this"):

```bash
python remember_explicit.py --text "..." --scope global
```

It runs the text through the tiered validation chain and writes a local record only when the chain accepts it. It does not write Hindsight itself; the caller can persist the returned record through an MCP memory service.

## Relation to dsh-long-memory

`dsh-long-memory` is a separate, softer automatic-memory path: it distills each finished conversation turn and injects a digest into later sessions. It is useful for everyday preferences, project conventions, and pitfalls.

This pipeline is the stronger, explicit path: user-authorized memory, strict schema checks, tiered escalation, and an auditable result.

Recommended policy:

- explicit user memory > automatic suggestions
- automatic suggestions may be promoted after review
- automatic suggestions must not overwrite explicit memory

## Files

- `memory_pipeline.py` — tier router, model adapters, validators, VRAM wait/unload.
- `remember_explicit.py` — explicit-memory bridge.
- `pipeline.config.example.json` — configuration template.
- `examples/cases.example.json` — synthetic examples only.
- `tests/` — validator unit tests.

## Test

```bash
python -m unittest discover -s tests
```

## License

MIT. See `LICENSE`.

Prompt contracts and model weights belong to their original projects and are not redistributed here.
