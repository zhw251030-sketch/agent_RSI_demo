# State-generation runner independent review

Review date: 2026-10-21. Scope: source inspection of the new runner, its adapter/controller boundary and independent audit. No model request, candidate execution, task scoring, CSV read or sealed-task access was performed. Tests below only exercised the source-storage core.

## Findings

### 1. Prompt/tool mismatch — resolved before live requests

The two generation prompts requested `submit_initial_source`, but the actual SDK allowlist and system prompt expose `submit_candidate` and `finish`. This could waste a slot's sole request. Parent authorized the narrow correction. Both prompts now say `submit_candidate`.

Added `test_prompts_name_the_actual_sdk_submission_tool`: first failed on both planning and symbolic prompts, then passed after the wording correction. Full core suite: 19 passed, zero skipped. Evidence: `tmp/state-generation-toolname-red.txt`, `tmp/state-generation-core-green.txt`, and refreshed `tmp/state-generation-core-tdd.json` including current packet/source hashes.

### 2. Unhandled host exceptions bypass the required stopped-source freeze — corrected and re-reviewed

The initial version called `session_runner` without a per-slot host-exception boundary, and the final integrity `guard()` preceded `freeze_sources`. Exceptions escaped to `main`, which recorded `status=error` without creating `source-freeze.json`. A paid request prefix and already saved sources could remain outside the specified stopped-round freeze.

Concrete reachable boundaries include SDK `_validate_binding` before its local `try`, LLM construction in the runner closure, a failing conversation close/summary write, or the post-request integrity guard. Normal SDK-returned error summaries are handled; this finding concerns exceptions outside that returned-summary path. No further request is sent, so the issue is lost freeze/audit completion rather than extra model use.

The parent corrected the two reported paths. `session_runner` exceptions now produce an error-class-only host record, mark the affected slot blocked, stop subsequent slots and reach the source-tree freeze. The raw exception message is not copied. Post-request/per-slot guard failure now records `integrity_failed`, writes a create-only `unverified-source-snapshot.json` with `trusted:false`, and returns before trusted source freeze or static analysis. The audit continues to reject this integrity-failed state, so a snapshot is not misrepresented as certified evidence.

Read-only follow-up inspected both changed paths and the two added regression tests: `test_host_exception_preserves_prefix_and_freezes_stopped_run` and `test_runtime_tamper_after_request_preserves_unverified_snapshot_only`. Parent reported the runner suite passing 14/14 after red/green development; this reviewer did not rerun that suite. No further blocking finding remains within the requested review scope. A host exception that prevents SDK receipt/summary persistence can still leave a frozen but uncertifiable incomplete record; freezing does not synthesize missing transport evidence or guarantee that every infrastructure failure passes the strict auditor.

## Verified design boundaries

- `main` writes runtime, complete eight-slot inputs, historical source index, configuration, and generation settings before entering `execute` or constructing the request-serving session closure. A clean Git checkout is required for live mode.
- The input guard checks pinned runtime files, the raw frozen-input hash, canonical in-memory/frozen-input equality, historical-index file hash, and all source bindings before requests.
- Normal completion and handled SDK/usage failure paths freeze the complete current session tree before parsing any newly submitted source. Historical-source AST indexing happens earlier, using only historical artifacts; new source AST analysis does not drive resampling or acceptance.
- Unknown/invalid usage, unsettled reservations, halted controller/budget, or missing request identity stop following slots. Known-usage no-submission and response-contract failures remain missing and consume their original slots. No retry/resume path exists.
- `new_output` rejects an existing directory before returning it to `main`; hence its exception cannot cause `main` to rewrite an earlier run's summary. Source, candidate, phase-freeze and analysis artifacts use create-only writes. Atomic summary replacement is confined to the newly created run.
- Historical collision analysis binds the frozen index hash. The independent auditor additionally requires its exact `.py` inventory to match the frozen Git tree and checks actual historical bytes, Git blobs and recomputed source/AST hashes. This covers source-index provenance that the per-request guard alone does not recompute.
- The only task preparation path is the two previously public planning TaskViews (`seed0/problem0`, `seed0/problem1`). The source controller only writes bytes. The generation adapter exposes no task executor, terminal, file, browser or network tool; its business action archives source. New-source analysis uses `ast.parse`/`ast.dump`, never `exec`, `eval`, source import, fitting or evaluation. The broader imported planning module defines trusted VAL helpers, but the generation call chain only calls `prepare_task`.
- Four planning packets are identical across roles; the two dimension-3 symbolic packets are identical. Actor packets omit host allocation identifiers and symbolic metadata. Eight new requests are correctly not claimed to guarantee eight distinct or independent programs.

## Review limitations

The complete runner/SDK/audit suites are owned by the parent and SDK agent; this read-only review did not repeat them. The only executed tests were the authorized prompt regression and 19-test source-storage core suite. Saved hashes provide reproducibility, not provider authentication or independently attested timestamps. No future evaluator or strategy-update implementation was assessed or added.
