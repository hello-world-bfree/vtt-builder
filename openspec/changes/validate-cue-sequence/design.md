## Context

See `proposal.md` — Why, for the motivation and the four consumer sites that
hand-roll these invariants.

Design-relevant current state. **Referenced by symbol name, not line number**: an
unlanded VTT-parser branch adds ~230 lines to `src/lib.rs` ahead of most of these,
so any line number recorded here is stale on one side or the other of that merge.
Locate with `grep -n "fn <name>" src/lib.rs`.

- `validate_segment` is per-cue and takes a single `&Segment`, so it has no place
  to hold cross-cue state.
- `validate_segments` loops calling it, extracting each dict independently.
  Adding cross-cue checks here would change the meaning of an existing public
  function.
- `build_vtt_from_records` extracts and validates each segment inside one loop,
  pushing into `segments`, then calls `write_segments_to_vtt` — so a complete
  `Vec<Segment>` already exists before any write occurs. This is the natural
  insertion point.
- `File::create` happens *before* the extraction loop in both file builders. Any
  validation failure after that point leaves a truncated file behind.
- `build_vtt_from_json_files` differs in kind: it streams input files one at a
  time, validating and writing each before advancing a running `total_offset`. It
  never holds all segments at once. See the decision on it below.
- `build_vtt_from_records` and `build_vtt_from_json_files` name their validation
  flag `validate_segments`; `build_vtt_string` names its flag `validate`. The
  names are not interchangeable at the call site.
- The exception hierarchy is `VttError` → `VttValidationError` →
  `{VttTimestampError, VttHeaderError, VttCueError, VttEscapingError}`,
  registered in the `_lowlevel` module init.
- Timestamp formatting already round-trips through integer milliseconds
  (`format_timestamp_flexible`), and CLAUDE.md records the convention:
  "internal calculations use milliseconds as u64 to avoid floating-point errors."

## Goals / Non-Goals

**Goals**
- One authoritative implementation of the cue-sequence invariants.
- A distinguishable error type carrying enough detail to locate the bad pair.
- Builders that cannot silently emit a sequence-invalid file.
- A clamping transformation so callers can correct, not just detect.

**Non-Goals**
- Automatic repair of a bad sequence. Reordering or merging to make a malformed
  list valid would conceal the upstream bug this exists to surface. `clamp_to_duration`
  is the one exception, and only because bounding to a known media duration is
  unambiguous.
- Any line-wrapping or character-budget behavior (see proposal Non-goals).
- Changing what `validate_segments` means. It stays per-cue.

## Decisions

**Add a new function rather than extending `validate_segments`.**
`validate_segments` is public and documented as per-cue pre-validation. Silently
widening it would break callers who validate a list they intend to sort or clamp
afterwards. A separate `validate_cue_sequence` lets a caller choose, and lets the
builders compose both. Alternative: add a flag to `validate_segments`. Rejected —
a boolean that changes which invariants are checked is harder to read at the call
site than two named functions.

**Validate the whole sequence before opening the output file.**
`File::create` currently precedes extraction, so a mid-loop failure truncates
whatever was there. Restructure `build_vtt_from_records` to extract and validate
every segment first, and create the file only once the sequence is known good.
This is what makes the "no partial file is left behind" requirement true for
*validation* failures, and it also fixes the same hazard for the existing per-cue
errors.

**...and write via a temp file plus rename.**
Reversing an earlier decision in this document, which rejected temp-file-and-rename
as "unnecessary once validation precedes I/O." That reasoning closes the
validation window but not the I/O window. Once `File::create` succeeds, a
disk-full, a panic inside `write_segments_to_vtt`, or a `SIGKILL` still leaves a
partial file at the destination path — and the requirement as written in the spec
is unconditional: no output file is left where a caller could mistake it for a
successful build.

This is the **Write-Audit-Publish** pattern (Netflix; Ufford, DataWorks Summit
2017), described in **Data Engineering Design Patterns**: "it only changes the
output to write transformed records to a staging layer where an audit job can run
before eventually promoting the dataset to the final output location." The book
treats a partial artifact at the consumer-visible path as the failure WAP exists
to prevent.

Concretely: create the temp file in the *same directory* as the destination (so
the rename is same-filesystem and therefore atomic), write, then `fs::rename`
over the destination. Clean up the temp file on any error path.

Cost is a few lines and one extra `Drop`-guarded path. If that is judged not worth
it, the spec's "no partial file" scenario must be softened to cover validation
failures only — but it cannot be left claiming more than the code delivers.

**`build_vtt_from_json_files` is excluded from sequence validation.**
It streams input files one at a time, validating and writing each before advancing
`total_offset`, so it never holds the full segment list. Checking the sequence
per-file would enforce the invariant *within* each file and silently miss every
cross-file boundary — precisely where a bad offset shows up.

**Data Engineering Design Patterns** names this the *exhaustiveness rule*: do not
apply a validation function that cannot cover the scope it claims. The book takes
the same route for streaming ingestion, dropping its pre-write audit because "data
is continuously flowing to the system … This is a real-world example of the
exhaustiveness rule for validation functions." It separately warns that hoisting
the check earlier means "you'll risk reading the dataset twice."

So the options were: buffer every file's segments before any write (surrenders the
streaming property that is this function's reason to exist, with memory
proportional to total input), or validate a scope narrower than the guarantee
implies. Neither is acceptable, so this builder keeps per-cue validation only, and
that limit is stated in its docstring rather than left for a caller to discover.
A caller needing the cross-file guarantee reads the files, concatenates, and calls
`build_vtt_from_records`.

**Report the offending pair, not a boolean.**
The consumer's incidents were slow to diagnose because the proxy check reported
an aggregate ratio. The error message must name both cue indices and the
conflicting times so a failure is actionable from a log line alone. Follow the
existing message style, which prefixes with the segment id
(`"Segment {id}: ..."`).

**Compare quantized integer milliseconds, not raw `f64` seconds.**
Convert each `start`/`end` to `u64` milliseconds once, then compare exactly. Do
*not* compare raw `f64`, and do *not* introduce an absolute epsilon.

Three reasons, in order of weight:

1. *Floating-point absolute error scales with magnitude.* Per **Essential
   Mathematics for Games and Interactive Applications, 3rd Ed.** §1.4: "the
   absolute error of representation in a floating-point number is directly
   proportional to the magnitude of the value being represented … This is the
   opposite of what we saw with fixed-point numbers." A cue at t=0.5 and a cue at
   t=86400 do not have comparable representable spacing, so one fixed threshold
   cannot serve both.
2. *An absolute epsilon is the specific thing that book argues against.* §1.2.3
   "Precision and Error": a system accurate to within a kilometer is fine for the
   earth-sun distance and rounds an apple to zero, "yet in both cases the absolute
   error of representation is less than 1 km. Clearly, absolute error is not
   sufficient in all cases." Note the book's own comparison helper uses a *scaled*
   epsilon — `|a-b| <= eps*(|a|+|b|+1)` — not a bare one. Even that still requires
   choosing an epsilon and still yields no exact equality.
3. *Integers on the domain's natural grid compare exactly.* §1.2.2: "inside the
   range defined by the minimum and maximum representable integer values, all
   integers can be represented exactly." Cue times are millisecond-precision by
   WebVTT definition — the format itself serializes exactly 3 fractional digits —
   so milliseconds *are* the natural grid, and nothing below that grid is
   observable in the output.

This also conforms to a convention the crate already holds rather than forking
from it (CLAUDE.md: "internal calculations use milliseconds as u64 to avoid
floating-point errors"), and `format_timestamp_flexible` already quantizes the
same way on the write path.

Rejected alternative: raw `f64` with strict `<`. It is correct for *ordering*, but
`prev.end == next.start` after offset arithmetic is not reliably true, which
breaks the abutment rule below. Rejected alternative: absolute epsilon — see (2).

**Treat exact abutment as valid.**
`end == next.start` is the normal output of a well-behaved chunker, so it must
not be an error. A caller wanting separation passes `min_gap`. This is why gap
enforcement is opt-in rather than implied by overlap checking.

This rule **depends on the millisecond-quantization decision above**. In raw
`f64`, a chunker that computes `next.start` as `offset + delta` and `prev.end` as
a different expression can produce values that differ in the last bits, so exact
abutment would intermittently be reported as an overlap. Quantized to `u64` ms,
abutment is exact and the rule is implementable as stated. Gap comparison is
therefore `gap_ms < min_gap_ms` — strictly less than, so an explicit
`min_gap=0.0` still admits abutting cues.

**Reject zero-length cues in the sequence check, not the per-cue check.**
`validate_segment` permits `end == start` today (it only rejects `end < start`).
Tightening the per-cue check would be a wider breaking change affecting every
existing caller; scoping it to the new sequence validation keeps the blast radius
inside opt-in territory. Cost of this placement: a caller running only
`validate_segments` still admits zero-length cues, even though "is this cue
zero-length" is a per-cue property. Note it in both docstrings so the split is
discoverable.

**A free function over a slice, not a validated newtype.**
`check_cue_sequence(&[Segment], ...)` rather than a `ValidatedSequence` wrapper
with a smart constructor.

**Design Patterns and Best Practices in Rust** argues the general case the other
way, and does so strongly — "parse, don't validate" via newtypes, because with a
free function "you cannot inadvertently forget it" is exactly the property you
lose. That argument is accepted; it just does not bite here:

- The wrapper cannot cross the PyO3 boundary, so Python callers gain nothing.
- The book's own framing puts validation *at the system boundary*, and for this
  crate the `#[pyfunction]` layer **is** that boundary. A private
  `check_cue_sequence` called from each entry point is that pattern, minus a
  wrapper type with exactly one consumer.
- Nothing downstream consumes a validated sequence: `write_segments_to_vtt` is the
  only consumer, and it is reached directly from each builder. There is no
  interior codebase for the type to protect.

Caveat on sourcing: that book covers newtypes and boundary validation but says
nothing about FFI or PyO3 — asked directly, it returns nothing. The FFI half of
this reasoning is therefore judgment, not a sourced claim. Revisit if a future
change grows a Rust-internal call graph that passes segment lists between
functions, where forgetting the check becomes a live risk.

## Risks / Trade-offs

**Builders now reject input they previously accepted** → The intended behavior
change, and the point of the change, but it will surface latent bad data in
existing consumers on upgrade. Mitigated by `validate_segments=False` as an
escape hatch, and by a minor version bump with an explicit release note. Any
consumer that starts raising was already writing a malformed file.

**The transcription Lambda may begin raising on upgrade** → It enforces
monotonicity in four places, so its records are probably clean, but "probably" is
why this change exists. Before releasing, run the new validator against real
records from that consumer's caption and read-along paths and confirm they pass.
If they do not, that is a bug found — but it should be found deliberately, not by
a failed deploy.

**Restructuring the builder changes when I/O happens** → Moving `File::create`
after validation, and writing through a temp file, is a behavior change for the
error path only. Existing tests that assert a file exists after a failed build
would break; none is expected to, but it must be checked rather than assumed.

**Quantization changes which inputs are rejected at the boundary** → Two cues
whose `f64` times differ by less than half a millisecond collapse to the same
`u64` millisecond. A pair that abuts within sub-millisecond noise now compares
equal (valid), and a pair overlapping by less than half a millisecond now
compares equal rather than overlapping — so the validator is *marginally more
permissive* than a raw `f64` comparison at sub-millisecond scale. That is correct:
the WebVTT serialization has exactly 3 fractional digits, so a sub-millisecond
overlap is not representable in the output file and cannot affect a player.
A zero-length check must run on the *quantized* values for the same reason — a
cue spanning 0.0001s is zero-length once written.

**Temp-file writes change the failure surface** → The destination directory must
be writable for the temp file, not just the destination path. On most paths that
is identical, but a caller writing to a directory where they can create a
specific file and not arbitrary ones would newly fail. Judged acceptable and
vanishingly rare; note it in the release note.

## Migration Plan

1. Implement and test with no builder wiring, so the validator can be run against
   real consumer data before anything changes behavior.
2. Validate real records from the transcription Lambda's caption and read-along
   paths. Resolve any failures before proceeding.
3. Wire the check into `build_vtt_from_records` and `build_vtt_string`;
   restructure so validation precedes `File::create`, and write through a temp
   file plus rename. `build_vtt_from_json_files` is out of scope — see the
   decision above.
4. `make version VERSION=0.6.0`, `make test`, `make lint`, release.
5. Update the consumer separately to retire `clamp_vtt_records` and replace the
   `check_vtt_integrity` proxy.

Rollback is a version pin: consumers stay on 0.5.0, which has neither the new
functions nor the builder change.

## Open Questions

- Should `min_gap` eventually default to a small non-zero value rather than
  being opt-in? Deferrable — it changes no requirement here, and the answer is
  better informed once real consumer data has been run through the validator.
- Should the sequence invariants also be property-tested (`proptest`) rather than
  only covered by the enumerated boundary cases in `tasks.md` §6.1? Ordering and
  overlap are naturally expressible as properties over a generated sorted list.
  Left open deliberately: the enumerated cases are the ones the consumer
  incidents actually produced, and no source was found to argue the trade-off.
  Flagged rather than answered.
- Does `build_vtt_from_json_files` eventually deserve a non-streaming sibling
  that does guarantee the cross-file invariant? Only worth doing if a consumer
  asks; the concatenate-then-`build_vtt_from_records` workaround is two lines.
