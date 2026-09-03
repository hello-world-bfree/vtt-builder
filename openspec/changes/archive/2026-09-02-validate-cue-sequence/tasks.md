> **Line numbers deliberately omitted.** An unlanded VTT-parser branch shifts
> most of `src/lib.rs` by ~230 lines, so recorded line numbers would be wrong on
> one side or the other of that merge. Locate symbols with
> `grep -n "fn <name>" src/lib.rs`.

## 1. Add the sequence error type

- [x] 1.1 Add `create_exception!(vtt_builder, VttSequenceError, VttValidationError)`
      alongside the existing exception declarations at the top of the file, so a
      caller catching `VttValidationError` still catches it.
- [x] 1.2 Add a `sequence_error(msg: &str) -> PyErr` helper matching the existing
      `timestamp_error` / `cue_error` / `header_error` style.
- [x] 1.3 Register the type in the `_lowlevel` module init next to the other
      exceptions.
- [x] 1.4 Re-export `VttSequenceError` from `python/vtt_builder/__init__.py` and
      add it to `__all__`.

## 2. Implement the sequence validator

- [x] 2.1 Write a private `check_cue_sequence(segments: &[Segment], min_gap: Option<f64>, audio_duration: Option<f64>) -> PyResult<()>`
      operating on an already-extracted slice, so both the public function and
      the builders can call it without re-extracting dicts. Free function over a
      slice, not a validated newtype — see design.md for why the newtype the Rust
      patterns literature would recommend does not pay here.
- [x] 2.2 **Quantize first.** Convert every `start`/`end` to `u64` milliseconds
      once, up front, and run every comparison below on the quantized values.
      Do not compare raw `f64`; do not add an epsilon. Rationale and sources in
      design.md — floating-point absolute error scales with magnitude, so no
      single epsilon serves both a cue at t=0.5 and one at t=86400, whereas
      milliseconds are the grid the WebVTT format itself serializes.
      Reuse the existing rounding behavior so this agrees with
      `format_timestamp_flexible` — a value that writes as `00:00:01.500` must
      quantize to `1500`.
- [x] 2.3 Reject a cue whose `start` precedes the previous cue's `start`
      (out of order).
- [x] 2.4 Reject a cue whose `start` precedes the previous cue's `end` (overlap).
      Treat `start == prev.end` as valid — exact abutment is normal chunker
      output, and is exact once quantized.
- [x] 2.5 Reject a cue whose quantized `start == end` (zero-length, never
      displayed). Note this catches a cue spanning less than half a millisecond,
      which is correct: it serializes to a zero-length cue.
- [x] 2.6 When `min_gap` is given, reject an adjacent pair separated by less than
      it. Compare `gap_ms < min_gap_ms` — strictly less than, so an explicit
      `min_gap=0.0` still admits abutting cues.
- [x] 2.7 When `audio_duration` is given, reject a cue starting at or after it,
      and a cue ending after it.
- [x] 2.8 Include both cue indices (and segment ids) plus the conflicting times
      in every message, so a log line alone locates the fault. Report the
      *original* times in messages, not the quantized integers — a reader
      matching a log line against input data needs the values they passed in.
- [x] 2.9 Return `Ok(())` for an empty or single-cue list — no pair exists.

## 3. Expose the public validator

- [x] 3.1 Add `#[pyfunction]` `validate_cue_sequence` with
      `#[pyo3(signature = (segments_list, min_gap=None, audio_duration=None))]`,
      extracting via the existing `extract_segment_data` and delegating to
      `check_cue_sequence`.
- [x] 3.2 Return `true` on success, matching the convention of
      `validate_segments` and `validate_vtt_file`.
- [x] 3.3 Register in module init and re-export from the Python wrapper with
      `__all__` updated.
- [x] 3.4 Write the rustdoc block in the established style: summary, `# Arguments`,
      `# Returns`, and a `# Example` python block. State that comparisons are at
      millisecond precision, and that zero-length cues are rejected here but not
      by `validate_segments` — add the mirror note to `validate_segments`' own
      docstring so the split is discoverable from either side.

## 4. Implement clamp_to_duration

- [x] 4.1 Add `#[pyfunction]` `clamp_to_duration(segments_list, audio_duration)`
      returning a new list, following the `merge_segments` shape for dict
      extraction and rebuilding.
- [x] 4.2 Truncate `end` to `audio_duration` when it overruns; leave `start`
      untouched.
- [x] 4.3 Omit cues whose `start >= audio_duration`.
- [x] 4.4 **Emit only `id`/`start`/`end`/`text`; extra keys are dropped.** This
      corrects an earlier version of this task, which asked to preserve
      `speaker`/`confidence` "consistent with the other transformations" — they
      are not preserved anywhere. `merge_segments` rebuilds dicts with exactly
      those four keys, `extract_segment_data` returns a 4-tuple, and `Segment`
      has four fields, so extra keys are structurally unable to survive any
      current transformation. Dropping them is the consistent behavior;
      preserving them in `clamp_to_duration` alone would make it the outlier.
      Document the drop in the rustdoc.
- [x] 4.5 Register and re-export as above.
- [x] 4.6 If preserving extra keys is wanted, raise it as its own change covering
      every transformation together — it needs a passthrough-dict path that no
      transformation has today, and doing it piecemeal is what creates the
      inconsistency this task just had to correct.

## 5. Wire validation into the builders

- [x] 5.1 **Restructure `build_vtt_from_records` so all extraction and validation
      completes before `File::create`.** It currently creates the file ahead of
      the extraction loop, so any validation failure leaves a truncated file
      behind. This is what makes "no partial file" true for validation failures,
      and it fixes the same hazard for the existing per-cue errors.
- [x] 5.2 **Write through a temp file plus atomic rename.** Reverses a decision
      design.md originally rejected: validate-then-open closes the validation
      window but not the I/O window, so a disk-full or panic inside
      `write_segments_to_vtt` still leaves a partial file at the destination.
      Create the temp file in the *same directory* as the destination (so the
      rename is same-filesystem and atomic), write, then `fs::rename` into place.
      Remove the temp file on every error path. This is Write-Audit-Publish; see
      design.md for the source.
      If this is judged not worth the complexity, say so explicitly and soften
      the spec's "no partial file" scenarios to cover validation failures only —
      do not leave the spec claiming more than the code delivers.
- [x] 5.3 In `build_vtt_from_records`, call `check_cue_sequence` after the
      extraction loop when its `validate_segments` **parameter** is true, with
      `min_gap` and `audio_duration` left as `None` so only ordering, overlap,
      and zero-length are enforced by default. Note the parameter shadows the
      same-named `validate_segments` pyfunction inside this body — the bool is
      what is in scope, which is existing behavior, but read it deliberately.
- [x] 5.4 Apply the same to `build_vtt_string`, whose flag is named **`validate`**,
      not `validate_segments`. The two builders differ here; do not assume one
      name.
- [x] 5.5 Confirm the opt-out skips the sequence check as well as the per-cue
      checks in both builders (`validate_segments=False` and `validate=False`
      respectively), preserving the prior behavior exactly.
- [x] 5.6 **Leave `build_vtt_from_json_files` on per-cue validation only** — do
      not add the sequence check. It streams input files one at a time and writes
      each before reading the next, so it never observes the whole sequence; a
      per-file check would enforce the invariant inside each file and silently
      miss every cross-file boundary, which is exactly where a bad offset appears.
      Per the exhaustiveness rule cited in design.md, a check narrower than the
      guarantee it implies is worse than none.
- [x] 5.7 Document that limit in `build_vtt_from_json_files`' rustdoc: it
      validates cues, not ordering across files, and a caller needing the
      cross-file guarantee should concatenate the records and call
      `build_vtt_from_records`. Without this note the divergence between the two
      file builders is silent, which is the failure mode this task exists to
      avoid.

## 6. Tests

- [x] 6.1 Rust unit tests in the existing `mod tests` block for
      `check_cue_sequence`: valid ordered list, overlap, out-of-order, exact
      abutment (valid), zero-length, gap violation, duration overrun, start past
      end, empty list, single cue.
      **Written, but they do not execute.** The crate is `crate-type = ["cdylib"]`
      with pyo3's `extension-module` feature, so `cargo test` fails at link time
      ("symbol(s) not found for architecture arm64" — no Python interpreter to
      link against). This is pre-existing: neither the Makefile nor CI has ever
      run `cargo test`, and `cargo clippy --all-targets` silently skips the test
      target for the same reason, so these tests are not even lint-checked.
      Every case here is therefore mirrored in the Python suite (6.2), which is
      what actually verifies the behavior. See 6.8.
- [x] 6.1a Quantization cases, the cover for 2.2: a pair abutting only after
      rounding passes; a pair overlapping by less than half a millisecond passes;
      a cue spanning less than half a millisecond is rejected as zero-length;
      `min_gap=0.0` admits abutting cues. These are the regression cover for
      choosing millisecond comparison over raw `f64` — without them a later
      refactor back to `f64` comparison passes the suite.
- [x] 6.1b A cross-file case for 5.6: two files whose within-file cues are valid
      but whose boundary overlaps, built via `build_vtt_from_json_files`, does
      **not** raise. This pins the documented limit so it cannot be "fixed"
      accidentally into a half-guarantee.
- [x] 6.2 Python tests in `tests/test_vtt_builder.py` following the existing
      `TestX` class convention: one class per new function.
- [x] 6.3 Test that `VttSequenceError` is caught by `except VttValidationError`
      and is *not* raised for single-cue faults.
- [x] 6.4 Test that a rejected file build leaves no file at the destination path
      — the regression cover for 5.1.
- [x] 6.4a Test that a rejected build over an **existing** valid file leaves that
      file intact and unmodified — the cover for the temp-file write in 5.2, and
      the case a caller is most likely to hit in production.
- [x] 6.4b Test that no temp file is left in the destination directory after a
      rejected or failed build.
- [x] 6.5 Test that `validate_segments=False` still writes an overlapping
      sequence.
- [x] 6.6 Test `clamp_to_duration` round-trips into `validate_cue_sequence`
      cleanly for an ordered input.
- [x] 6.7 Confirm the pre-existing tests still pass; investigate any that assumed
      a file exists after a failed build.
      **One did, and it was a real intended break.**
      `TestEdgeCases::test_zero_duration_segment` built a file from
      `{"start": 1.0, "end": 1.0}` and asserted the zero-length cue appeared in
      the output. Sequence validation now rejects that input, which is the
      point — no player ever displays such a cue. Split into
      `test_zero_duration_segment_rejected` (expects `VttSequenceError`) and
      `test_zero_duration_segment_written_when_validation_disabled` (pins the
      opt-out), with a docstring recording the 0.6.0 behavior change.
      Also: the "168" in the original wording was wrong. 19 of those 168 are the
      new parser tests from the same uncommitted branch; the pre-parser baseline
      was 149. Suite is now **212 passed, 0 skipped**.
- [ ] 6.8 **Decide whether to make the Rust unit tests runnable**, or delete them
      rather than leave 21 tests that look like cover and provide none. Options:
      add `"rlib"` to `crate-type` so a test harness can link; or gate the pyo3
      `extension-module` feature behind a non-test cfg (the standard maturin
      pattern); or move the pure logic into a small inner module with no pyo3
      types and test that. Not done here — it changes the crate's build shape,
      which is outside this change's scope and deserves its own decision.
      Whichever way it goes, `make test` should run whatever exists, so a green
      "tests pass" means every test actually ran.

## 7. Verify against real consumer data

- [x] 7.1 **Before wiring section 5 into a release**, run `validate_cue_sequence`
      against real records from the transcription Lambda's caption and
      read-along paths. Per design.md, this is how a latent bad sequence gets
      found deliberately instead of by a failed deploy.
      **Run against 9 production VTT files under `$HOME/dev/transcription/`
      (`data/` and `__data/`), parsed with `parse_vtt_file`. 7 pass, 2 fail.**

      | File | Cues | Span | Result |
      |---|---|---|---|
      | `__data/line_miss_ex1.vtt` | 90 | 9.1m | ok |
      | `__data/line_miss_ex2.vtt` | 157 | 14.0m | ok |
      | `data/deepgram-year-issue/captions.vtt` | 93 | 10.0m | ok |
      | `data/deepgram-year-issue/transcript.vtt` | 8 | 10.0m | ok |
      | `data/test_mov_content/…/failed_transcript.vtt` | 84 | 10.8m | ok |
      | `data/test_mov_content/…/transcript.vtt` | 87 | 10.8m | ok |
      | `data/test_re_enrich/output/captions.vtt` | 118 | 9.7m | **overlap** |
      | `data/test_re_enrich/output/transcript.vtt` | 91 | 9.7m | **overlap** |
      | `data/transcript.vtt` | 120 | 14.7m | ok |
- [x] 7.2 If any real record set fails, stop and report it — that is a consumer
      bug this change just surfaced, and it should be triaged before release.
      **Reported. The two failures are ONE defect, and it is NOT a live consumer
      bug — it is a stale artifact. Triage below; it does not block release.**

      Identical fault in both files, one overlapping pair each, read straight
      from the raw `.vtt` (so not a parser artifact):

      ```
      00:05:38.500 --> 00:05:50.005     ends   350.005
      00:05:48.820 --> 00:06:11.810     starts 348.820   overlap 1.185s
      ```

      Traced upstream:

      ```
      Deepgram raw paragraphs  -->  0 overlaps
      Deepgram raw words       -->  3 overlaps   <-- true origin
        'as'     [169.475->171.795] then 'pride'     start 170.120
        'humble' [387.705->388.825] then 'listening' start 388.360
        "that's" [576.820->578.900] then "today's"   start 577.385
           |
           v
      enriched_segments.json   -->  1 overlap (end 350.00509433962264, interpolated)
           +--> captions.vtt   -->  1 overlap
           +--> transcript.vtt -->  1 overlap
      ```

      **Why it does not block:** all four hand-rolled enforcers were read and
      each one *does* fix this pair. Traced the exact branch for
      `enforce_min_cue_gap` with the real numbers: `MIN_CUE_GAP=0.1`,
      `MIN_CAPTION_DURATION=0.75`, `new_end=348.72`,
      `would_shrink_below_min=False`, `new_end > prev_start=True` → takes the
      shrink-`prev.end` branch → overlap fixed. `_enforce_monotonic_chunks` is
      also the last phase of `chunk_for_vtt` (chunker.py PHASE 5) and fixes it
      too.

      The artifacts are simply older than the guards:

      ```
      captions.vtt / transcript.vtt   2026-01-14
      enriched_segments.json          2026-01-17
      chunker.py                      2026-08-30   <-- guards are ~7 months newer
      vtt_utils.py                    2026-08-30
      ```

      So the corpus caught a **genuine historical defect** that current code
      already prevents. That is the validator doing its job, and it is also
      why design.md's "its records are probably clean" was right about the
      live path and wrong to be confident.

      **Still worth filing in the consumer** (not this repo): Deepgram emits
      non-monotonic *word* timings, and nothing asserts on them at ingest —
      `extract_word_timings` feeds them straight into alignment. The guards
      repair the symptom downstream; nothing reports the cause. A
      `validate_cue_sequence` assertion at the word-timing boundary would.
- [x] 7.3 Record the outcome in the change before archiving, so the next reader
      knows whether real data was ever exercised.
      **Done — 7.1 and 7.2 above are that record.** Real data was exercised: 9
      files, 848 cues total. One historical defect found, root-caused to
      Deepgram word timings, confirmed already-fixed in current consumer code.

      **Second, independent run against S3 production artifacts — corroborates
      7.2's triage.** Run separately, against a different corpus, using the
      *published* 0.6.0 wheel from PyPI rather than a local build:

      | | |
      |---|---|
      | Corpus | 120 artifacts / 60 media, pulled from `s3://hallow-audio` |
      | Selection | all written >= 2026-08-25, i.e. **after** the 2026-08-30 guards |
      | Both artifact types | `captions.vtt` 55/55 pass, `transcript.vtt` 65/65 pass |
      | Adjacent cue pairs | 17,934 |
      | out_of_order / overlap / zero_length | **0 / 0 / 0** |
      | Most negative gap observed | `0.0` |

      This is the direct confirmation 7.2's triage predicted but could not show:
      it argued the two overlaps were *stale artifacts* older than the guards,
      not a live defect. A post-guard corpus returning zero overlaps across
      17,934 pairs is that argument tested against current output. The two runs
      agree — the historical corpus catches the old defect, the current corpus
      shows it no longer occurs.

      Cross-check of the implementation itself: a reference implementation of
      the spec'd invariants, written independently before this record was read,
      agreed with the shipped library on **all 120 files, zero disagreements**.

      Also confirmed on this corpus, the ms-quantization decision (design.md):

      ```
      naive raw-f64  min_gap=0.1  ->  119/120 files fail
      shipped 0.6.0  min_gap=0.1  ->   10/120 files fail
      ```

      94% of the naive failures were float representation noise (the consumer
      emits gaps of exactly 0.1s; `6.560000 - 6.460000 == 0.09999999999999964`).
      The 10 genuine failures all have a smallest gap of **exactly 0 ms** — real
      abutment, correct output. That settles design.md's open question: `min_gap`
      must stay opt-in, never a non-zero default, or correct abutting cues are
      rejected. 218 such abutting pairs appear in this corpus.

      Spec conformance of the shipped wheel: **28/28** scenarios from
      `specs/cue-sequence-validation/spec.md` verified against 0.6.0 from PyPI,
      including error-hierarchy separation (`VttSequenceError` caught by
      `except VttValidationError`; a negative timestamp still raises
      `VttTimestampError`), no-partial-file, existing-file-survives, and the
      `validate_segments=False` / `validate=False` opt-outs.

      Consumer impact of upgrading: transcription suite on 0.6.0 is
      **824 passed / 1 failed / 33 skipped — byte-identical to 0.5.0**. The one
      failure is a pre-existing test pinning 0.2.1's "id required" contract.
- [x] 7.4 **Define what "real records" concretely means before starting 7.1**, or
      this task gets checked off on nothing.
      **Chosen: a scratch script run against the consumer repo's own
      `data/`/`__data/` VTT corpus, with results pasted into 7.1/7.2 above.**
      No fixture was committed to this repo — the corpus is 9 real files
      totalling ~1.4MB of customer transcript text, which does not belong in an
      open-source library's test fixtures. Reproduce with the script in the
      session scratchpad (`validate_real_records.py`), or re-derive it: glob
      `**/*.vtt` under the consumer's `data/` and `__data/`, `parse_vtt_file`
      each, then `validate_cue_sequence`.
- [ ] 7.5 Include at least one record set from a long-duration item (an hour or
      more) in whatever 7.4 selects. Sub-millisecond drift is magnitude-dependent,
      so a short clip cannot exercise the quantization behavior that 2.2 chose.
      **NOT SATISFIED.** Longest item in the available corpus is **14.7 minutes**
      (881.6s); the whole corpus spans 8–15 minutes. Nothing here exercises
      timestamps where f64 spacing has grown enough to matter, which is the
      entire premise of the millisecond-quantization decision in 2.2. The
      synthetic cover in `TestCueSequenceQuantization::
      test_long_duration_timestamps_compare_correctly` uses 7200s (2h) and
      passes, but synthetic is not the same as a real hour-long episode with
      real accumulated interpolation error. Left open deliberately: find a
      long-form episode before treating §7 as fully discharged.

      **Partially advanced, still NOT satisfied.** The S3 corpus added in 7.3
      extends the longest real item from 14.7 min to **44.4 minutes** (2664s,
      1078 cues) and adds 5 items over 30 minutes, all passing. That is 3x the
      previous reach and well past where f64 spacing at ms scale starts to
      matter — but it is still not the hour-plus this task asks for. 0 of 120
      items in that corpus exceed 60 minutes.

      Keep open. The gap is narrower than it was, not closed.

## 8. Release

- [x] 8.1 `make test` — full suite green. Report skips explicitly rather than
      counting them as passes.
- [x] 8.2 `make lint` — `ruff check` plus `cargo clippy --all-targets -D warnings`.
- [x] 8.3 `make format`.
- [x] 8.4 `make version VERSION=0.6.0` (updates `Cargo.toml`, `pyproject.toml`,
      and `python/vtt_builder/__init__.py` together).
- [x] 8.5 Update `README.md` and `docs/ARCHITECTURE.md` for the new functions and
      the builder behavior change. Both files already exist at those paths —
      `docs/` predates the global "docs live in `__docs/`" preference, so follow
      the repo (Rule 11) rather than relocating docs as a side effect of this
      change.
- [x] 8.6 Write the release note covering all four user-visible changes, not just
      the first:
      1. **BREAKING** — `build_vtt_from_records` and `build_vtt_string` now
         reject sequence-invalid input by default; `validate_segments=False` /
         `validate=False` is the escape hatch.
      2. `build_vtt_from_json_files` is deliberately **not** covered, and why —
         a consumer relying on the multi-file path gets no new guarantee and
         should not infer one from the headline.
      3. Sequence comparisons are at millisecond precision, so sub-millisecond
         overlaps no longer count as overlaps.
      4. File builders now write via a temp file and rename, so the destination
         directory must be writable, not just the destination path.
- [x] 8.7 Confirm the release build produces the cp313 `manylinux_2_17_aarch64`
      wheel the consumer's Lambda ARM64 runtime requires.
      **Confirmed on PyPI, not just in CI artifacts:**
      `vtt_builder-0.6.0-cp313-cp313-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`
      (plus a musllinux aarch64 sibling). 0.6.0 published 2026-09-03; 115 files
      on PyPI. Verified by installing from PyPI in a clean env: version reports
      0.6.0, the new API is present, an overlapping list raises
      `VttSequenceError`, and `validate=False` still writes it.

      Three release-infrastructure bugs were found and fixed along the way, all
      of which would have blocked or corrupted the release:
      1. `macos-13` runner label was retired — jobs targeting it queue forever
         instead of failing fast, stalling three runs (one for 6h39m). Intel
         macOS wheels are no longer built; Apple Silicon still is.
      2. `uv publish` globs `dist/*`, but `download-artifact` unpacked to the
         working directory root, so it found nothing. Fixed with `path: dist`.
      3. **Two workflows both published on `release: published`** (`maturin.yml`
         and `release.yml`), which would have raced once (2) was fixed — the
         loser failing with "File already exists" on a release that actually
         succeeded. `release.yml` is now the sole publisher; `maturin.yml`'s
         release job is manual-dispatch only. `release.yml` also gained the
         `environment: pypi` gate it was missing.

## 9. Follow-up in the consumer (not this repo)

- [ ] 9.1 File the transcription-side work: retire `clamp_vtt_records`
      (`lib/vtt_utils.py:281`) in favor of `clamp_to_duration`, and replace the
      statistical `check_vtt_integrity` proxy with a real
      `validate_cue_sequence` assertion.
- [ ] 9.2 Note that its four hand-rolled monotonicity enforcers
      (`word_aligner.py:311`, `timing_mapper.py:371`, `chunker.py:502`,
      `vtt_utils.py:415`) can then assert rather than hope — but they still
      *enforce*, since this library deliberately does not repair.
