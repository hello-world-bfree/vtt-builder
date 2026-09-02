## Purpose

Validates a cue list as an ordered sequence — covering ordering, overlap,
inter-cue gaps, and media-duration bounds — as distinct from per-cue field
validation, and guarantees that the builders which receive a complete cue list
refuse to write a file whose cues are individually valid but collectively
malformed. Comparisons are made at the millisecond precision the WebVTT format
serializes.

## ADDED Requirements

### Requirement: Cue sequences are validated for ordering and overlap
The library SHALL provide a way to validate a cue list as a sequence. The
validation SHALL reject a list in which any cue starts before its predecessor
starts, or starts before its predecessor ends.

#### Scenario: Cues are correctly ordered and disjoint
- **WHEN** a cue list is validated in which each cue starts at or after the end
  of the cue before it
- **THEN** validation succeeds

#### Scenario: A cue starts before its predecessor ends
- **WHEN** a cue list is validated in which one cue's start time is earlier than
  the end time of the cue before it
- **THEN** validation fails with a sequence error identifying the two cues
  involved and their conflicting times

#### Scenario: Cues are out of chronological order
- **WHEN** a cue list is validated in which one cue's start time is earlier than
  the start time of the cue before it
- **THEN** validation fails with a sequence error identifying the two cues
  involved

#### Scenario: Adjacent cues abut exactly
- **WHEN** a cue list is validated in which one cue starts at exactly the end
  time of the cue before it, and no minimum gap is requested
- **THEN** validation succeeds, because abutting cues do not overlap

#### Scenario: Times differing below millisecond precision are treated as equal
- **WHEN** a cue list is validated in which one cue's start time precedes its
  predecessor's end time by less than half a millisecond
- **THEN** validation succeeds, because cue times are compared at the
  millisecond precision the WebVTT format serializes, and a difference finer
  than that cannot appear in the output file

### Requirement: Cue times are compared at millisecond precision
The sequence validation SHALL compare cue times quantized to whole
milliseconds, so that two times which serialize identically in a WebVTT file
compare as equal regardless of the floating-point arithmetic that produced them.

#### Scenario: Abutment survives floating-point arithmetic
- **WHEN** a cue list is validated in which a cue's start time and its
  predecessor's end time were computed by different arithmetic but denote the
  same millisecond
- **THEN** validation succeeds, and does not report an overlap

#### Scenario: A cue is zero-length only after quantization
- **WHEN** a cue list is validated in which one cue's start and end times differ
  by less than half a millisecond
- **THEN** validation fails with a sequence error identifying the cue, because
  the cue has zero duration once written to a WebVTT file

#### Scenario: A list too short to have a sequence
- **WHEN** an empty cue list or a single-cue list is validated
- **THEN** validation succeeds, because no cue pair exists to conflict

### Requirement: A minimum inter-cue gap can be required
The sequence validation SHALL accept an optional minimum gap and, when one is
given, SHALL reject any adjacent cue pair separated by less than that gap.

#### Scenario: All gaps meet the minimum
- **WHEN** a cue list is validated with a minimum gap, and every adjacent pair
  is separated by at least that gap
- **THEN** validation succeeds

#### Scenario: A gap is smaller than the minimum
- **WHEN** a cue list is validated with a minimum gap, and one adjacent pair is
  separated by less than that gap
- **THEN** validation fails with a sequence error identifying the pair and the
  observed gap

#### Scenario: No minimum gap is requested
- **WHEN** a cue list of abutting cues is validated without a minimum gap
- **THEN** validation succeeds

### Requirement: Cue times can be bounded by media duration
The sequence validation SHALL accept an optional media duration and, when one is
given, SHALL reject any cue that starts at or after that duration or ends after
it.

#### Scenario: All cues fall within the media duration
- **WHEN** a cue list is validated against a media duration and every cue ends
  at or before it
- **THEN** validation succeeds

#### Scenario: A cue ends after the media duration
- **WHEN** a cue list is validated against a media duration and one cue's end
  time exceeds it
- **THEN** validation fails with a sequence error identifying the cue and the
  overrun

#### Scenario: A cue starts past the end of the media
- **WHEN** a cue list is validated against a media duration and one cue's start
  time is at or after it
- **THEN** validation fails with a sequence error identifying the cue

### Requirement: Zero-length cues are rejected
The sequence validation SHALL reject any cue whose start and end times are
equal, because such a cue is never displayed.

#### Scenario: A cue has zero duration
- **WHEN** a cue list is validated in which one cue's start and end times are
  equal
- **THEN** validation fails with a sequence error identifying the cue

### Requirement: Sequence faults are distinguishable from per-cue faults
A sequence validation failure SHALL raise an error type distinct from those
raised for single-cue field faults, and that type SHALL belong to the existing
validation error hierarchy so that callers catching validation errors broadly
continue to catch it.

#### Scenario: A caller distinguishes fault kinds
- **WHEN** a caller catches the sequence error type specifically
- **THEN** it catches sequence faults and does not catch single-cue field faults
  such as a negative timestamp or empty cue text

#### Scenario: A caller catches validation errors broadly
- **WHEN** a caller catches the general validation error type
- **THEN** it catches sequence faults as well as single-cue field faults

### Requirement: Builders refuse to write a sequence-invalid file
When validation is enabled, the builders that receive a complete cue list SHALL
apply sequence validation in addition to per-cue validation, and SHALL raise
rather than produce output. When validation is disabled, they SHALL apply
neither and preserve their prior behavior.

This requirement covers the builders that receive every cue before writing
anything. It SHALL NOT apply to the builder that streams input files one at a
time and writes each before reading the next: that builder cannot observe the
whole sequence, so it SHALL continue to apply per-cue validation only, and SHALL
document that limit.

#### Scenario: Building from an overlapping cue list with validation enabled
- **WHEN** a builder is called with validation enabled on a cue list containing
  an overlapping pair
- **THEN** it raises a sequence error and does not write a file or return content

#### Scenario: No partial file is left behind
- **WHEN** a file builder rejects a cue list for a sequence fault
- **THEN** no output file is left at the destination path, so a failed build
  cannot be mistaken for a successful one

#### Scenario: No partial file is left behind when writing fails midway
- **WHEN** a file builder accepts a cue list but the write itself fails partway
  through
- **THEN** no partially written file is left at the destination path, because
  content is written to a temporary location and moved into place only once it
  is complete

#### Scenario: An existing file survives a rejected build
- **WHEN** a file builder is called with a destination path that already holds a
  valid file, and the new cue list is rejected for a sequence fault
- **THEN** the existing file is left intact, because the destination is not
  opened or truncated until the cue list has passed validation

#### Scenario: A streaming multi-file builder validates each cue but not the sequence
- **WHEN** the builder that reads several input files in turn is called with
  validation enabled, and the cues within each file are individually valid but
  the last cue of one file overlaps the first cue of the next
- **THEN** it does not raise, because it never observes the two cues together,
  and its documentation states that it does not check cross-file ordering

#### Scenario: Building with validation disabled
- **WHEN** a builder is called with validation disabled on a cue list containing
  an overlapping pair
- **THEN** it writes the cues as given, preserving the prior behavior for
  callers that opt out

#### Scenario: Building a valid sequence
- **WHEN** a builder is called with validation enabled on a correctly ordered,
  non-overlapping cue list
- **THEN** it produces output as before, unchanged by this requirement

### Requirement: Cue times can be clamped to a media duration
The library SHALL provide a transformation that bounds every cue in a list to
lie within a given media duration, so that callers can correct out-of-range cues
rather than only detect them.

#### Scenario: A cue overruns the media duration
- **WHEN** a cue list is clamped to a media duration and one cue ends after it
- **THEN** that cue's end time is reduced to the media duration and its start
  time is unchanged

#### Scenario: A cue starts past the end of the media
- **WHEN** a cue list is clamped to a media duration and one cue starts at or
  after it
- **THEN** that cue is omitted from the result

#### Scenario: All cues already fall within the duration
- **WHEN** a cue list is clamped to a media duration and every cue already ends
  at or before it
- **THEN** the list is returned with all cues and times unchanged

#### Scenario: Clamping produces a validatable sequence
- **WHEN** an ordered, non-overlapping cue list is clamped to a media duration
- **THEN** the result passes sequence validation against that same duration
