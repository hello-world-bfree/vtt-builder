# vtt_builder

High-performance WebVTT file generation with spec compliance, powered by Rust.

## Features

- **Spec Compliant**: Automatic character escaping (`&`, `<`, `>`) per WebVTT specification
- **Fast**: Rust core with PyO3 bindings for optimal performance
- **Safe**: Input validation prevents malformed output
- **Multilingual**: Full Unicode support for Spanish, Portuguese, French, German, Italian, Polish, and more
- **Flexible**: Build from JSON files or Python dictionaries
- **Robust**: Comprehensive error handling with specific exception types
- **Versatile**: Rich set of transformation utilities (merge, split, shift, filter)
- **Insightful**: Built-in statistics and analysis functions
- **Podcast Ready**: Specialized functions for podcast transcription processing (filler removal, speaker diarization, confidence filtering, chapter detection)

## Installation

```bash
pip install vtt-builder
```

Or from source:

```bash
git clone https://github.com/hello-world-bfree/vtt-builder.git
cd vtt-builder
pip install -e .
```

## Quick Start

```python
from vtt_builder import build_vtt_from_records

segments = [
    {"id": 1, "start": 0.0, "end": 2.5, "text": "Hello world"},
    {"id": 2, "start": 2.5, "end": 5.0, "text": "This is a test"},
]

build_vtt_from_records(segments, "output.vtt")
```

Output:
```
WEBVTT

1
00:00:00.000 --> 00:00:02.500
Hello world

2
00:00:02.500 --> 00:00:05.000
This is a test
```

## Why Use VTT Builder?

### Automatic Character Escaping

WebVTT spec requires special characters to be escaped. VTT Builder handles this automatically:

```python
segments = [
    {"start": 0.0, "end": 2.0, "text": "Tom & Jerry"},
    {"start": 2.0, "end": 4.0, "text": "Math: 1 < 2"},
    {"start": 4.0, "end": 6.0, "text": "Use <html> tags"},
]
build_vtt_from_records(segments, "output.vtt")

# Output:
# Tom &amp; Jerry
# Math: 1 &lt; 2
# Use &lt;html&gt; tags
```

### Input Validation

Catch errors before they become problems:

```python
from vtt_builder import validate_segments, VttTimestampError

segments = [
    {"start": 5.0, "end": 2.0, "text": "Invalid!"},  # end < start
]

try:
    validate_segments(segments)
except VttTimestampError as e:
    print(f"Error: {e}")
    # "Segment 1: end time (2) must be >= start time (5)"
```

### Specific Error Types

```python
from vtt_builder import (
    VttError,           # Base exception
    VttValidationError, # General validation errors
    VttTimestampError,  # Timestamp issues
    VttHeaderError,     # Header format errors
    VttCueError,        # Cue content errors
)

try:
    validate_vtt_file("bad.vtt")
except VttTimestampError:
    # Handle timestamp-specific errors
    pass
except VttValidationError:
    # Handle any validation error
    pass
```

## Data Formats

### Segment Dictionary

```python
segment = {
    "id": 1,           # Optional (auto-generated if missing)
    "start": 0.0,      # Required: Start time in seconds
    "end": 2.5,        # Required: End time in seconds
    "text": "Hello"    # Required: Cue text content
}
```

### JSON File Format

```json
{
  "transcript": "Full text of the transcript",
  "segments": [
    {"id": 1, "start": 0.0, "end": 2.5, "text": "First segment"},
    {"id": 2, "start": 2.5, "end": 5.0, "text": "Second segment"}
  ]
}
```

## Functions

### `build_vtt_from_records(segments_list, output_file, escape_text=True, validate_segments=True)`

Build a VTT file from a list of Python dictionaries.

```python
segments = [
    {"start": 0.0, "end": 2.0, "text": "First cue"},
    {"start": 2.0, "end": 4.0, "text": "Second cue"},
]
build_vtt_from_records(segments, "output.vtt")
```

**Parameters:**
- `segments_list` (list[dict]): List of segment dictionaries
- `output_file` (str): Output file path
- `escape_text` (bool): Escape special characters (default: True)
- `validate_segments` (bool): Validate input data (default: True)

---

### `build_vtt_from_json_files(file_paths, output_file, escape_text=True, validate_segments=True)`

Build a VTT file from one or more JSON transcript files. Timestamps are automatically offset for continuous playback.

```python
build_vtt_from_json_files(
    ["part1.json", "part2.json", "part3.json"],
    "combined.vtt"
)
```

---

### `build_transcript_from_json_files(file_paths, output_file)`

Extract plain text transcripts from JSON files.

```python
build_transcript_from_json_files(
    ["part1.json", "part2.json"],
    "transcript.txt"
)
```

---

### `validate_vtt_file(vtt_file)`

Validate an existing WebVTT file for spec compliance.

```python
from vtt_builder import validate_vtt_file

try:
    validate_vtt_file("captions.vtt")
    print("Valid!")
except Exception as e:
    print(f"Invalid: {e}")
```

**Validates:**
- WEBVTT header (with BOM support)
- Timestamp formats (HH:MM:SS.mmm and MM:SS.mmm)
- Cue structure and content
- NOTE, STYLE, REGION blocks
- Cue settings (position, align, etc.)

---

### `validate_segments(segments_list)`

Pre-validate segment data before building.

```python
from vtt_builder import validate_segments

segments = load_from_database()
validate_segments(segments)  # Raises if invalid
build_vtt_from_records(segments, "output.vtt", validate_segments=False)
```

---

### `escape_vtt_text(text)`

Escape special characters for WebVTT compliance.

```python
from vtt_builder import escape_vtt_text

text = "Tom & Jerry say 1 < 2"
escaped = escape_vtt_text(text)
# "Tom &amp; Jerry say 1 &lt; 2"
```

---

### `unescape_vtt_text(text)`

Convert WebVTT escape sequences back to characters.

```python
from vtt_builder import unescape_vtt_text

text = "Tom &amp; Jerry"
original = unescape_vtt_text(text)
# "Tom & Jerry"
```

Supports: `&amp;`, `&lt;`, `&gt;`, `&nbsp;`, `&lrm;`, `&rlm;`

---

## Multilingual Support

Full Unicode support for international transcripts:

```python
segments = [
    {"start": 0.0, "end": 2.0, "text": "English: Hello!"},
    {"start": 2.0, "end": 4.0, "text": "Español: ¿Cómo estás?"},
    {"start": 4.0, "end": 6.0, "text": "Français: Ça va bien"},
    {"start": 6.0, "end": 8.0, "text": "Deutsch: Größe und Übung"},
    {"start": 8.0, "end": 10.0, "text": "Polski: Łódź i Kraków"},
    {"start": 10.0, "end": 12.0, "text": "Português: São Paulo"},
    {"start": 12.0, "end": 14.0, "text": "Italiano: Città"},
]
build_vtt_from_records(segments, "multilingual.vtt")
```

## Error Handling

```python
from vtt_builder import (
    build_vtt_from_records,
    VttTimestampError,
    VttCueError,
)

try:
    build_vtt_from_records(segments, "output.vtt")
except VttTimestampError as e:
    print(f"Timestamp error: {e}")
except VttCueError as e:
    print(f"Cue content error: {e}")
except IOError as e:
    print(f"File error: {e}")
```

## Advanced Usage

### Disable Validation (Performance)

```python
# Skip validation for trusted data
build_vtt_from_records(segments, "output.vtt", validate_segments=False)
```

### Disable Escaping (Raw Output)

```python
# Warning: May produce non-compliant VTT files
build_vtt_from_records(segments, "output.vtt", escape_text=False)
```

### Manual Escaping

```python
from vtt_builder import escape_vtt_text

# Pre-process text
text = "HTML: <div> & <span>"
clean = escape_vtt_text(text)
# "HTML: &lt;div&gt; &amp; &lt;span&gt;"
```

## Transformation Utilities

VTT Builder provides powerful utilities for transforming segment data:

### Merge Adjacent Segments

```python
from vtt_builder import merge_segments

segments = [
    {"start": 0.0, "end": 1.0, "text": "Hello"},
    {"start": 1.0, "end": 2.0, "text": "world"},
    {"start": 10.0, "end": 11.0, "text": "Separate"},
]

merged = merge_segments(segments, gap_threshold=0.5)
# [{"id": 1, "start": 0.0, "end": 2.0, "text": "Hello world"},
#  {"id": 2, "start": 10.0, "end": 11.0, "text": "Separate"}]
```

### Split Long Segments

```python
from vtt_builder import split_long_segments

segments = [
    {"start": 0.0, "end": 10.0, "text": "Very long text that exceeds character limits"}
]

split = split_long_segments(segments, max_chars=20)
# Multiple segments with proportional timestamps
```

### Shift Timestamps

```python
from vtt_builder import shift_timestamps

segments = [{"start": 0.0, "end": 2.0, "text": "Test"}]
shifted = shift_timestamps(segments, offset_seconds=10.0)
# [{"start": 10.0, "end": 12.0, "text": "Test"}]
```

### Filter by Time Range

```python
from vtt_builder import filter_segments_by_time

segments = [
    {"start": 0.0, "end": 5.0, "text": "Early"},
    {"start": 10.0, "end": 15.0, "text": "Middle"},
    {"start": 20.0, "end": 25.0, "text": "Late"},
]

filtered = filter_segments_by_time(segments, start_time=8.0, end_time=18.0)
# [{"start": 10.0, "end": 15.0, "text": "Middle"}]
```

### Timestamp Conversion

```python
from vtt_builder import seconds_to_timestamp, timestamp_to_seconds

timestamp = seconds_to_timestamp(3661.123)
# "01:01:01.123"

seconds = timestamp_to_seconds("01:01:01.123")
# 3661.123
```

### Statistics

```python
from vtt_builder import get_segments_stats

segments = [
    {"start": 0.0, "end": 2.0, "text": "Hello world"},
    {"start": 2.0, "end": 5.0, "text": "This is a test"},
]

stats = get_segments_stats(segments)
# {
#   "total_duration": 5.0,
#   "num_segments": 2,
#   "avg_duration": 2.5,
#   "total_words": 6,
#   "words_per_second": 1.2,
#   ...
# }
```

### In-Memory VTT Building

```python
from vtt_builder import build_vtt_string

segments = [{"start": 0.0, "end": 2.0, "text": "Hello"}]
vtt_content = build_vtt_string(segments)
# Returns WebVTT string without writing to disk
```

## Podcast Transcription Processing

VTT Builder is optimized for processing podcast transcriptions from services like Deepgram, OpenAI Whisper, and AssemblyAI.

### Remove Filler Words

Clean up transcriptions by removing verbal fillers:

```python
from vtt_builder import remove_filler_words

segments = [
    {"start": 0.0, "end": 2.0, "text": "Um so basically I think"},
    {"start": 2.0, "end": 4.0, "text": "You know like it's actually good"},
]

cleaned = remove_filler_words(segments)
# [{"text": "so I think", ...},
#  {"text": "it's good", ...}]

# Custom fillers
custom = remove_filler_words(segments, fillers=["well", "right", "okay"])
```

### Speaker Diarization

Group segments by speaker with WebVTT voice tags:

```python
from vtt_builder import group_by_speaker

segments = [
    {"start": 0.0, "end": 1.0, "text": "Hello", "speaker": "Alice"},
    {"start": 1.0, "end": 2.0, "text": "world", "speaker": "Alice"},
    {"start": 2.0, "end": 3.0, "text": "Hi there", "speaker": "Bob"},
]

grouped = group_by_speaker(segments)
# [{"text": "<v Alice>Hello world", "speaker": "Alice", ...},
#  {"text": "<v Bob>Hi there", "speaker": "Bob", ...}]
```

### Confidence Filtering

Filter out low-confidence transcription segments:

```python
from vtt_builder import filter_by_confidence

segments = [
    {"start": 0.0, "end": 2.0, "text": "Clear speech", "confidence": 0.95},
    {"start": 2.0, "end": 4.0, "text": "Mumbled", "confidence": 0.4},
]

# Remove low confidence segments
filtered = filter_by_confidence(segments, min_confidence=0.8)
# Only keeps "Clear speech"

# Or mark them for review
marked = filter_by_confidence(segments, min_confidence=0.8, remove_or_mark="mark")
# Adds "low_confidence": True flag
```

### Word-Level to Segment Aggregation

Convert word-level timestamps to sentence-like segments:

```python
from vtt_builder import words_to_segments

# Output from Deepgram/Whisper word-level API
words = [
    {"word": "Hello", "start": 0.0, "end": 0.5},
    {"word": "world.", "start": 0.6, "end": 1.0},
    {"word": "How", "start": 1.5, "end": 1.8},
    {"word": "are", "start": 1.9, "end": 2.1},
    {"word": "you?", "start": 2.2, "end": 2.5},
]

segments = words_to_segments(words, max_segment_duration=10.0, pause_threshold=1.0)
# Groups words into segments based on punctuation and pauses
```

### Remove Repeated Phrases

Clean up stuttering and repetitions:

```python
from vtt_builder import remove_repeated_phrases

segments = [
    {"start": 0.0, "end": 2.0, "text": "I think I think I think it's good"},
]

cleaned = remove_repeated_phrases(segments)
# [{"text": "I think it's good", ...}]
```

### Automatic Chapter Detection

Detect chapter breaks based on pauses:

```python
from vtt_builder import detect_chapters

segments = [
    {"start": 0.0, "end": 60.0, "text": "Introduction..."},
    {"start": 61.0, "end": 180.0, "text": "Main topic..."},
    {"start": 190.0, "end": 300.0, "text": "Different topic..."},  # 10s gap
]

chapters = detect_chapters(segments, min_chapter_duration=60.0, silence_threshold=5.0)
# [{"chapter": 1, "start": 0.0, "timestamp": "00:00"},
#  {"chapter": 2, "start": 190.0, "timestamp": "03:10"}]
```

### Complete Podcast Processing Pipeline

```python
from vtt_builder import (
    words_to_segments,
    remove_filler_words,
    remove_repeated_phrases,
    filter_by_confidence,
    group_by_speaker,
    build_vtt_from_records,
)

# Raw transcription from API
raw_words = api_response["words"]

# Process pipeline
segments = words_to_segments(raw_words)
segments = remove_filler_words(segments)
segments = remove_repeated_phrases(segments)
segments = filter_by_confidence(segments, min_confidence=0.7)
segments = group_by_speaker(segments, format_speaker=True)

# Generate clean VTT
build_vtt_from_records(segments, "podcast_episode.vtt")
```

## Documentation

- [API Reference](docs/API.md) - Complete function documentation
- [Architecture](docs/ARCHITECTURE.md) - Internal design and structure

## Requirements

- Python 3.8+
- Rust toolchain (for building from source)

## Testing

```bash
pytest tests/ -v
```

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## Version History

- **0.5.0** - Podcast processing: filler removal, speaker diarization, confidence filtering, word aggregation, chapter detection
- **0.4.0** - Transformation utilities: merge, split, shift, filter, stats, in-memory building
- **0.3.0** - WebVTT spec compliance: character escaping, input validation, custom exceptions
- **0.2.1** - Handle multiple newlines, tabs, carriage returns
- **0.2.0** - Support NOTE and STYLE blocks
- **0.1.0** - Initial release
