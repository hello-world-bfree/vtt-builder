## Why

Validation in this crate is strictly per-cue. `validate_segment` checks negative
timestamps, `end < start`, empty text, and a literal `-->`. Nothing checks a cue
*against its neighbours*: `validate_segments` loops cue-by-cue with no cross-cue
state, so a list whose cues are each individually valid but collectively out of
order, overlapping, or past the end of the media passes validation and is written
to disk as a malformed VTT — silently, with a success return.

(Symbols in this document are referenced by name rather than line number: an
unlanded VTT-parser branch shifts most of `src/lib.rs` by ~230 lines.)

That is the failure mode that actually reaches production. In the primary
consumer (the Hallow transcription Lambda), cue-sequence invariants are
hand-enforced in four separate places, each with its own clamping and edge cases:

| Consumer site | Invariant enforced |
|---|---|
| `alignment/word_aligner.py:311` `_enforce_monotonic` | word times non-decreasing |
| `alignment/timing_mapper.py:371` `_enforce_monotonic_segments` | segments non-overlapping |
| `alignment/chunker.py:502` `_enforce_monotonic_chunks` | chunks non-overlapping |
| `lib/vtt_utils.py:415` `enforce_min_cue_gap` | minimum gap between cues |

Four implementations of "a later cue must not begin before an earlier one ends."
Because the library offers no way to *assert* the result, that consumer resorts
to a statistical proxy — counting cues below a duration threshold and measuring
what fraction of the audio the cue span covers — and treats a bad ratio as
evidence of a timing bug. A proxy is what you write when the real invariant is
too expensive to check in Python; in Rust it is a linear scan.

Multiple incidents in that consumer produced VTT files whose individual cues were
all valid and whose sequence was not. In each case the library was handed a bad
sequence and wrote it out without complaint.

## What Changes

- **A new `validate_cue_sequence` function** checks a segment list for
  cross-cue invariants: non-decreasing start times, no overlap between adjacent
  cues, an optional minimum gap, an optional upper bound from media duration,
  and no zero-length cues. It reports the offending cue pair rather than a
  boolean.
- **A new `VttSequenceError`** joins the existing hierarchy under
  `VttValidationError`, so callers can distinguish a sequence fault from a
  single-cue fault without string matching.
- **The builders refuse to emit a sequence-invalid file.** When validation is
  enabled — already the default — `build_vtt_from_records` and `build_vtt_string`
  run the sequence check in addition to the existing per-cue checks. This turns a
  class of silent corruption into a build-time error. **BREAKING**: input that
  previously produced a malformed file now raises. Passing
  `validate_segments=False` (or `validate=False` for `build_vtt_string`, which
  names its flag differently) preserves the old behavior.
  `build_vtt_from_json_files` is deliberately **excluded**: it streams input files
  one at a time and never observes the whole sequence, so a check there would
  cover only within-file ordering while implying more. See design.md.
- **Cue times are compared at millisecond precision**, quantized to `u64` rather
  than compared as raw `f64`. This matches the precision WebVTT actually
  serializes and the convention the crate already holds on the write path, and it
  is what makes the "exact abutment is valid" rule reliable rather than
  arithmetic-dependent.
- **File builders write via a temp file and rename**, so a validation failure or
  a failed write cannot leave a partial file where a caller would read it as a
  success.
- **A new `clamp_to_duration`** transformation bounds every cue to
  `[0, audio_duration]`, dropping cues that start past the end and truncating
  cues that overrun it. The consumer reimplements exactly this
  (`vtt_utils.py:281` `clamp_vtt_records`) and must remember to call it on every
  path, which is how one path comes to forget.

## Capabilities

### New Capabilities
- `cue-sequence-validation`: Validation of a cue list as an ordered sequence —
  ordering, overlap, inter-cue gap, and media-duration bounds — as distinct from
  the existing per-cue field validation, including the guarantee that the
  builders will not write a sequence-invalid file.

### Modified Capabilities
<!-- None. This repository has no specs under openspec/specs/ yet, so there are
     no existing capability requirements to modify. The behavior change to the
     builders is captured as a requirement of the new capability above. -->

## Impact

**Code**
- `src/lib.rs` — add `validate_cue_sequence`, `clamp_to_duration`, and
  `VttSequenceError`; register all three in the `_lowlevel` module init; call the
  sequence check from `build_vtt_from_records` and `build_vtt_string`, and
  restructure both file builders to validate before opening the destination and
  to write through a temp file.
- `python/vtt_builder/__init__.py` — re-export the two functions and the
  exception, and add them to `__all__`.
- `tests/test_vtt_builder.py` — new cases for each invariant, plus cover for the
  builder now refusing a bad sequence.
- Rust unit tests in the `mod tests` block for the pure sequence logic.

**Consumers**
- The transcription Lambda can retire `clamp_vtt_records` and replace the
  statistical `check_vtt_integrity` proxy with a real assertion. That is a
  follow-up in that repository, not part of this change; it currently pins
  `vtt-builder>=0.5.0`.
- Any consumer relying on the builders accepting an out-of-order list must set
  `validate_segments=False`.

**Versioning**
- Minor bump to `0.6.0` via `make version VERSION=0.6.0`. The breaking element is
  gated behind an existing opt-out flag, but the default-path behavior change
  warrants the release note.

**Non-goals**
- No line wrapping or character-budget behavior. `split_long_segments` already
  covers character splitting and is deliberately not extended here; the primary
  consumer is actively removing character-budget logic from its caption path.
- No replacement of the consumer's chunking. `words_to_segments` is not extended
  to cover word-count caps, sentence boundaries, or domain-specific merge rules,
  which are consumer concerns.
- No automatic repair. This change validates and, via `clamp_to_duration`,
  bounds. It does not reorder or merge cues to fix a bad sequence — silently
  repairing a malformed sequence would hide the upstream bug this is meant to
  surface.
- No preservation of extra segment keys. `clamp_to_duration` emits
  `id`/`start`/`end`/`text` only, matching every existing transformation —
  `Segment` has four fields and `extract_segment_data` returns four values, so no
  transformation carries `speaker` or `confidence` today. Making them survive is
  a separate change that should cover all transformations at once.
- No cross-file sequence guarantee for `build_vtt_from_json_files`, per above.
