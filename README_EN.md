# DSH Memory Pipeline

Tiered memory processing for DeepSeek Harness (DSH). Run a small local model first, validate strictly, and escalate only when needed.

Default route:

Q4 -> 9B -> 27B -> Strata -> cloud

The pipeline handles two jobs:

- **Fact extraction** - turn evidence segments into structured facts.
- **Fact admission** - decide whether a candidate fact should pass, be revised, dropped, or held.

It is not a full memory database. It produces validated JSON; storage and retrieval belong to your memory backend.

## Why tiering

The Q4 model is fast and cheap for most items. Larger models are only called when the small model's output fails deterministic validation.

Every tier must pass:

- valid JSON
- required fields
- evidence IDs exist
- valid fact type
- valid decision
- `revise` has a non-empty replacement
- `drop` / `hold` has no replacement
- `pass` / `revise` has evidence

Q4 gets one repair attempt. If it still fails, the next tier runs.

## Low-VRAM behavior

Local models are not kept resident after a batch.

- A failed Ollama tier is unloaded before the next tier.
- At the end of a run, Q4/9B/27B models used by the run are unloaded.
- Available VRAM is checked before loading a tier.
- If VRAM is insufficient, the pipeline polls every 10 seconds and waits up to 30 minutes.
- It does not close games or other models. It only waits, then skips the tier if the timeout expires.

## Start from a tier

```bash
python memory_pipeline.py --cases examples/cases.example.json --start q4
python memory_pipeline.py --cases examples/cases.example.json --start 9b
python memory_pipeline.py --cases examples/cases.example.json --start 27b
python memory_pipeline.py --cases examples/cases.example.json --start strata
python memory_pipeline.py --cases examples/cases.example.json --start cloud
```

Earlier tiers are skipped.

## Setup

1. Install Ollama and the desired models.
2. Download the memory-model prompts and Modelfiles from:
   - https://github.com/lifdjgfndgn/qwen3.5-4b-memory-v2
   - https://huggingface.co/IMLIULIAN/qwen3.5-4b-memory-v2
3. Place that project at `vendor/qwen3.5-4b-memory-v2-main`, or update `prompts_dir` in the config.
4. Copy `pipeline.config.example.json` to `pipeline.config.json`.
5. Adjust model names and endpoints.

The prompt contracts belong to the Qwen3.5-4B-Memory-V2 project (Apache-2.0). This repository does not redistribute model weights.

## Cloud tier

The cloud tier is an OpenAI-compatible adapter.

Set:

- `MEMORY_CLOUD_BASE_URL`
- `MEMORY_CLOUD_MODEL`
- `DEEPSEEK_API_KEY`, or the key environment named in the config

If the key is missing, the cloud tier is skipped.

A DSH account route such as `deepseek-account/deepseek-flash` only works inside a signed-in DSH session. An external process cannot use it directly; use an API key, or integrate the pipeline as a DSH plugin.

## Explicit-memory bridge

`remember_explicit.py` handles user-authorized memory ("remember this"):

```bash
python remember_explicit.py --text "..." --scope global
```

It runs the text through the tiered validation chain and writes a local record only when the chain accepts it. It does not write Hindsight itself; the caller can persist the returned record through an MCP memory service.

## Relation to dsh-long-memory

`dsh-long-memory` is a softer automatic path: it distills each finished conversation turn and injects a digest into later sessions. It is suitable for everyday preferences, project conventions, and pitfalls.

This pipeline is the stronger explicit path: user-authorized memory, strict schema checks, tiered escalation, and an auditable result.

Recommended policy:

- explicit user memory > automatic suggestions
- automatic suggestions may be promoted after review
- automatic suggestions must not overwrite explicit memory

## Files

- `memory_pipeline.py` - tier router, adapters, validators, VRAM wait/unload.
- `remember_explicit.py` - explicit-memory bridge.
- `pipeline.config.example.json` - configuration template.
- `examples/cases.example.json` - synthetic examples only.
- `tests/` - validator unit tests.

## Test

```bash
python -m unittest discover -s tests
```

## License

MIT. See `LICENSE`.

Prompt contracts and model weights belong to their original projects and are not redistributed here.
