# Qwen3.8-max Windows reproduction

This recipe targets the Bird OpenAI-compatible gateway and the 48 Windows v1
tasks in this repository. The tested task baseline is commit
`50334aafe1090c13829b604bdfa9d2a30180e884`, proposed in
[PR #19](https://github.com/Touchstone-AI-Lab/OS-Omni/pull/19). This configuration
PR is stacked on that branch so checking it out includes the tested repairs.
See [application compatibility](task-application-compatibility.md) before
building a fresh VM, especially the OpenTrip inventory and DeltaChat profiles.

## Model and wire settings

| Setting | Value |
| --- | --- |
| Base URL | `https://birdapi.up.railway.app/v1` |
| Actual HTTP call | `POST https://birdapi.up.railway.app/v1/chat/completions` |
| Provider / model | `openai` / `qwen3.8-max` |
| Credentials | `OPENAI_API_KEY`, provided locally |
| Maximum output | `max_completion_tokens=16384` |
| Streaming | `stream=true` |
| API screenshot encoding | Full-resolution JPEG, quality 85 |
| Stored screenshots | Original PNG, unmodified |
| Historical text window | 3 completed steps |
| Historical image window | 0; retain only the current screenshot |
| Task limits | `max_steps=300`, `timeout=180` |
| Action / observation | `code_adapter` / `screenshot_only` |

Two model presets and execution files are provided:

| Preset | Flat wire fields | Execution |
| --- | --- | --- |
| `qwen3_8_max_low` | `reasoning_effort=low`, `enable_thinking=true` | `executions/v1/windows_qwen3_8_max_low.yaml` |
| `qwen3_8_max_no_thinking` | `reasoning_effort=none`, `enable_thinking=false` | `executions/v1/windows_qwen3_8_max_no_thinking.yaml` |

Both omit the generic `reasoning` object, including `generate_summary`.
The no-thinking preset checks the **raw** `reasoning_content` before parsing
the response. A provider that returns thinking produces an explicit ERROR.
Requested SSE responses must contain a `finish_reason` and `[DONE]` terminal
event; an incomplete action is not accepted as a complete provider response.

These presets concern Qwen3.8 **Max**. The separately discussed Together names
`red-lobster-7636/qwen-test1` and `red-lobster-7636/qwen-test2` identify other
dedicated deployments and are not called by this recipe.

## Local configuration

Use Python 3.12 or 3.13 and the repository dependencies from `pyproject.toml`.
The API-only probe uses `httpx`, `python-dotenv`, `PyYAML` and Pillow.

Copy `configs/windows/qwen38-max.env.example` to the ignored `.env.qwen38` file.
Fill `OPENAI_API_KEY` through the existing credential channel or the process
environment. Populate the VM path, clean snapshot name, runtime token and guest
credentials for the selected machine. Empty API-key fields do not overwrite an
already supplied environment key. An empty VM password denotes an unencrypted
VM configuration.

The validated runtime used port **5001**. It had a 1920x1080 desktop, Windows 11,
two virtual CPUs, 4 GB memory and VMware Workstation 17.5.2. Select a snapshot
with the current Windows runtime and required task apps ready; restore it
between tasks. The VM's private path, snapshot identifier and credentials are
machine-specific and belong in the ignored environment file.

The source image was `YUNTA88/os_win` on Hugging Face. Its original encrypted
VMware configuration rejected the supplied password in the tested environment;
the experiment used a separate bootable VM with the disk chain flattened and
a runtime-ready snapshot. Do not assume a freshly downloaded VMX is equivalent
to that prepared snapshot. Preserve original image assets when preparing a VM.

Only one experiment may control a given VM at a time. On the shared host, check
whether another model's experiment owns the VM before launching a reset. API
probes and request replays do not touch the VM.

## API-only probes

From the repository root, first verify a minimal text request:

```powershell
python tools/windows/probe_qwen38_max.py --env-file .env.qwen38 --model qwen3_8_max_low --case text
```

Then use an existing screenshot from the prepared guest. This runs text,
single-screenshot and multi-turn requests, with one current screenshot:

```powershell
python tools/windows/probe_qwen38_max.py --env-file .env.qwen38 --model qwen3_8_max_low --screenshot <screenshot.png>
```

To reproduce the original no-thinking requirement, select
`--model qwen3_8_max_no_thinking`. To probe two images in a multi-turn request,
add `--case multi --image-history-window 1`. That synthetic probe repeats the
provided image. A successful synthetic probe does not establish that a full
task request or a different screenshot will succeed.

Each probe uses a 180-second request timeout and **zero automatic retries**.
It reports the requested/returned model, finish reasons, reasoning-character
count when available, usage if reported and redacted request metadata. Image
data is replaced with digests. It saves a uniquely named JSON file under
`artifacts/qwen38/`, which is ignored by Git. It never executes returned actions.

### Replay a real failed request

The provider can record actual requests/responses with
`OS_OMNI_LLM_EXCHANGE_LOG`. Keep this evidence local. Its request records omit
authorization headers and replace image data with hashes; they still contain
benchmark instructions and model outputs.

Given one attempt's exchange log and its original screenshots:

```powershell
python tools/windows/probe_qwen38_max.py --env-file .env.qwen38 --model qwen3_8_max_low --replay-log <attempt>/llm-exchanges.jsonl --image-root <attempt>
```

The last exchange is selected by default. `--exchange-index 1` selects the
second exchange (zero-based). The helper restores exact JPEG image hashes,
preserves the recorded messages and requires model, effort, thinking flag,
token cap and URL to match the chosen preset/profile. It sends the key only to
the configured gateway. Neither replayed replies nor earlier task actions are
executed. It fails if original image evidence is missing.

## Run a Windows task or the 48-task execution

After the API gate is stable, test a single real task from the selected clean
snapshot. Create a local execution under ignored `artifacts/qwen38/` by copying
the chosen execution YAML and narrowing its `tasks` list to one existing task.
The historically failing tasks are:

* `tasks/v1/windows/blender_robot_tower_layout_scene.yaml`
* `tasks/v1/windows/calc_crosssheet_chart.yaml`

The same entry point accepts that local single-task YAML or the provided
48-task execution. To load the profile explicitly before invoking the normal
Windows CLI, run this in PowerShell from the repository root:

```powershell
@'
from pathlib import Path
from tools.windows.probe_qwen38_max import load_profile
load_profile(Path('.env.qwen38'))
from platforms.windows.cli import main
raise SystemExit(main(['--execution', 'executions/v1/windows_qwen3_8_max_low.yaml']))
'@ | python -
```

The CLI starts tasks serially, performs normal initialization and snapshot
reset, and stores normal result/trajectory/screenshot artifacts under
`results/windows/<model>/...`. This is the standard CLI, not the earlier local
supervisor that stopped after two consecutive provider ERRORs. Its suite may
continue after a failed task. Use a one-task YAML while investigating errors.

The 180-second timeout is **not a whole-task deadline**. Formal runs used two
outer provider attempts; the adapter can make up to three HTTP attempts per
invocation for transient errors. A single step can therefore take much longer than 180
seconds. The image-history setting is an environment override and must reach
the child processes, not just exist in an execution description.

## Known observations, 2026-11-03

* Explicit no-thinking requests returned HTTP 200 with nonempty raw
  `reasoning_content`. Earlier parsing hid that field; the new guard detects it.
* Text requests accepted all tested effort strings. Real multi-turn requests
  with two screenshots still timed out or returned 502; changing effort alone
  did not establish a working configuration.
* With only the latest screenshot, low/medium/xhigh probes returned complete
  replies. The low formal run completed Actual Budget in 73 steps and passed
  its evaluator.
* Blender subsequently timed out at step 2. Calc's step-2 reply lacked a
  terminal stream event. One full-task infrastructure retry of each reproduced
  the same error, despite a separate Calc replay succeeding in about 94 seconds.
* That low queue ended with **1 PASS, 2 ERROR, 45 pending**, not a completed
  48-task result. Provider-aborted tasks were excluded from model scoring.

Resolve the gateway's intermittent timeout/stream termination behavior before
calling the 48-task experiment stable. Preserve failed evidence and task
definitions. A thinking run and a no-thinking run are separate configurations;
changing effort requires a separate result record.

## Agent acceptance checks

1. Verify preset and actual wire fields; reproduce text, screenshot, multi-turn
   and an actual failed request with original image evidence when available.
2. Distinguish HTTP/stream/mode errors from normal model FAIL results. Preserve
   raw evidence locally and report unavailable token usage as unknown.
3. Keep no-thinking and terminal-event validation intact while fixing transport.
   Complete the real failing task probe before launching the 48-task execution.

Offline regression checks:

```powershell
python -m pytest tests/test_openai_sse_response.py tests/test_openai_image_encoding.py tests/test_qwen38_max_probe.py tests/test_benchmark_runner_utf8.py tests/test_openai_system_prompt_as_user.py -q
```
