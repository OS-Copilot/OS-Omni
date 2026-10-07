# Linux tasks on a headless QEMU VM

The Linux agent can operate a graphical desktop inside a headless VM. The host
does not need a display: screenshots and input travel through the guest runtime.

## Prepare the VM

1. Download and verify the [Linux v3 image](https://huggingface.co/datasets/Cloudriver/OS-Omni-VM/tree/main/linux/v3).
   Keep the complete extracted VMDK chain. Convert the active descriptor
   `Ubuntu-cl3-compact-000001.vmdk` with `qemu-img convert -f vmdk -O qcow2`;
   this incorporates its parent disk. Create a writable QCOW2 overlay backed by
   the converted disk.
2. Boot the overlay with QEMU/KVM, a virtual display, `-display none`, a QMP Unix
   socket, and guest network forwarding. For example, use
   `-qmp unix:/path/to/qmp.sock,server=on,wait=off`. Keep forwarded ports bound to
   the host loopback interface. KVM can also be exposed to a QEMU container via
   `--device /dev/kvm`.
3. In the guest's logged-in X11 session, start
   `platforms/linux/guest/runtime_server.py` with the dependencies from
   `platforms/linux/guest/requirements.txt`. Select an unused guest port, set
   `DISPLAY` to the desktop display, and verify `/health` reports `HEALTHY` and
   screenshots show the desktop. If launching through another Flask server,
   remove inherited `WERKZEUG_*` environment variables first.
4. Set the desktop resolution to 1920×1080 and disable automatic screen locking.
   Save a clean QEMU snapshot using the monitor command `savevm baseline` after
   the runtime is ready and before any task runs.

The supplied image contains one active disk state. Historical VMware snapshot
names in TaskSpec metadata are provenance; converting the disk does not recreate
those snapshots. Record the actual baseline used and retain initializer failures
when task prerequisites are not satisfied.

## Connect a local vision model

`configs/models.yaml` includes `qwen3_8_27b_local`, an OpenAI-compatible endpoint
for Qwen3.8-27B. Run a vision-capable inference server with the served model name
`Qwen/Qwen3.8-27B`, then set:

```bash
export QWEN_LOCAL_BASE_URL=http://127.0.0.1:18038/v1
export QWEN_LOCAL_API_KEY=EMPTY
export OS_OMNI_LINUX_RUNTIME_TOKEN=your-guest-runtime-token
```

Use a separate environment for the inference server and its GPU dependencies.
The Linux controller includes the guest user's `~/.local/bin` in bash steps so
preinstalled user tools such as Node are available to initializers and evaluators.

The model configuration uses temperature 1.0, top-p 0.95, a 4096-token output
limit, and `medium` reasoning effort. Its `computer_use_protocol: qwen` metadata
selects the Linux Qwen planner: the model returns XML `computer_use` calls with
coordinates from 0 to 1000, and the planner converts them to actual screen pixels.
The native tool call and converted action are retained in the trajectory. This
follows the [Qwen action protocol in OSWorld](https://github.com/xlang-ai/OSWorld/tree/main/mm_agents/qwen);
it does not reproduce the complete OSWorld agent or its benchmark scores.
Record server-side settings separately, including whether thinking is
enabled, the model revision, precision, context length, and inference engine.
The default execution retains three previous steps, so the server must accept
at least four images per request.

## Run v1 Linux

With the VM and inference server running:

```bash
python scripts/run_linux_qemu_batch.py \
  --execution executions/v1/linux.yaml \
  --model qwen3_8_27b_local \
  --output-dir /path/to/experiment/results \
  --qmp-socket /path/to/qmp.sock \
  --snapshot baseline \
  --runtime-port 15001
```

Use `--task-id linux.opencode.sk2_hook_debug_commit` for a single-task smoke test.
`--resume` reuses completed task artifacts whose task, model configuration, and
run settings match. A changed model checkpoint or VM baseline requires a new
output directory even when their names are unchanged. Interrupted tasks without
a completed result also require a fresh output directory.

For parallel runs, give each worker its own VM and QMP socket, select disjoint
task IDs with repeated `--task-id` arguments, and use a different
`--summary-file /path/to/shard-summary.json` for each worker. Workers may share
an output directory only when their task IDs do not overlap.

The runner restores the baseline before every task, waits for runtime health,
and runs the original initializer, agent, and evaluator. It honors each TaskSpec's
step limit and timeout. Each task directory contains `runner.log`, screenshots,
`trajectory.jsonl`, and `result.json` when the episode completes. `summary.json`
tracks progress and separates task verdicts from initialization, evaluation,
execution, and VM infrastructure errors. A completed batch is not necessarily
a successful benchmark; inspect the summary counts.

Some imported v1 tasks still reference unavailable initializer or evaluator
modules. These produce errors and cannot contribute a valid model success-rate
measurement until the original implementations and prerequisites are available.
