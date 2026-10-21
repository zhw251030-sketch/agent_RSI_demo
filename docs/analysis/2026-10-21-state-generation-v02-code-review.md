# State-generation v0.2: independent runner and history review

Reviewed on 2026-10-21 at local Git HEAD `de372716c517db9a53db8b97b14ad21f8440dc26`. Scope: `scripts/run_state_generation_v02.py`, its new protocol/configuration, their reuse of the frozen v0.1 runner, and v0.1 archive/runtime immutability. The new transport wrapper and v0.2 auditor were delegated separately and are not certified by this review.

Result: no blocking finding in the reviewed root-owned scope. Exact file hashes and verification counts are in `tmp/state-generation-v02-review.json`. No production file was changed, no credential read, no API/model/SDK session called, no candidate executed, and no task dataset opened.

## Effective model and batch boundaries

Read-only calls to the pure configuration functions confirm that the public model configuration and its hash are identical. The only changed effective model field is `timeout: 60 -> 180`. Effective `num_retries=0`, `stream=false`, `fallback_strategy=null`, model identity, temperature and output limit remain unchanged. The unchanged v0.1 input builder supplies the same eight slot definitions, anonymized task packets and 8-request/5-CNY budget with one request per slot.

The new configuration is checked against an exact literal schema: old manifest digest, base configuration path, CPython3.12.14, SDK1.55.1, whole-new-batch, no retry/resume, and zero candidate/strategy execution. The protocol explicitly forbids splicing the two old sources into a new batch, starting an automatic third batch after another stop, or interpreting infrastructure completion as RSI improvement.

## Freeze and execution chain

- Live mode verifies SDK1.55.1 before preparation. Preparation verifies CPython3.12.14, the fixed old manifest hash and the exact new batch configuration.
- Preparation reuses the v0.1 clean-checkout runtime freeze, adds the v0.2 protocol, and writes runtime/input/history/config/batch/settings before any credential resolution or model call. The base runtime inventory includes new Python, JSON and prompt files and matching state-generation test files.
- `new_output` retains exclusive directory creation and rejects any existing run. This also means prepare-only and the later live batch need separate run IDs; prepare-only is a separate zero-call inspection artifact, not a resumable batch.
- Live credentials are resolved only after preparation. The session closure checks the saved batch-freeze digest, builds the same bounded generation adapter and invokes one SDK session under the new transport context. There is no additional model-call loop or retry in this runner. Actual enforcement and receipt fidelity inside that context remain subject to the transport agent's tests/review.
- The original `execute` function remains byte-identical. Its input/runtime guards, unknown-usage stop, missing-slot handling, host-exception preservation, integrity-failed snapshot and freeze-before-new-source-AST ordering therefore carry over. No new candidate evaluator, fitting step, planner execution or strategy update is introduced.
- The prior source index naturally includes v0.1's archived sources through the unchanged historical `.py` inventory. It is kept in host records and is not included in the task packet.
- New report version is v0.2. Independent validation of the v0.2 batch hash, actual transport receipts and effective settings must be supplied by the separately implemented v0.2 auditor; this review does not treat the old v0.1 auditor as applicable to the new report.

## Historical byte verification

The v0.1 manifest SHA256 remains `c8b249c5c8bbbcff497e86536309e5f6cfbf7ca8b4eac59871101d778466086c`, matching both the frozen v0.2 literal and the current committed archive.

All **43** raw archive files match the manifest byte hashes. The exact inventory has zero missing or extra raw files; `README.md` and `manifest.json` are the two declared supplementary files. Raw-tree digest remains `769fa632ad992506f2276d6d79ceb9c4891de1ad1f4b4549c153f698cd4577e5`.

All **131** v0.1 runtime files match both current local bytes and their Git blobs at `cb40fee10a6f1f589328f8e3f8cbcc926b644c0d`. The runtime-freeze file SHA256 remains `43184af84b64453095ce3d45714929809af6a72c3d7e5e438b3905b21013f65e`; the canonical runtime hash-map SHA256 is `6813316471388175de0516fbfaef62095fcb8ef0317b004aacf703c1d2189c77`. New runtime files are permitted additions and do not alter this original inventory.

Tracked changes in the old runtime/config/prompt/fixture/artifact scopes are zero. New v0.2 files were untracked at review time, so live operation must still wait for the parent's ordinary commit/synchronization and clean-checkout verification. This is an implementation-state observation, not a request for additional user permission.

## Limits

The review verifies configuration behavior, source call paths, file inventories and hashes. It does not infer the timeout's cause, guarantee an end-to-end 180-second deadline, establish provider-side retry behavior, or claim that future generated sources will be valid or useful. Unit/SDK/transport/audit suites and the one authorized live batch are owned by the parent and other agents; no extra tests or paid calls were performed here.
