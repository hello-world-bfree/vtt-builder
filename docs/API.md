# VTT Builder API Reference

Complete API documentation for the VTT Builder library.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Builder Functions](#builder-functions)
- [Validation Functions](#validation-functions)
- [Utility Functions](#utility-functions)
- [Exception Types](#exception-types)
- [Data Formats](#data-formats)
- [Configuration Options](#configuration-options)
- [Examples](#examples)

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

Output (`output.vtt`):
```
WEBVTT

1
00:00:00.000 --> 00:00:02.500
Hello world

2
00:00:02.500 --> 00:00:05.000
This is a test
```

---

## Builder Functions

### `build_vtt_from_records`

Build a WebVTT file from a list of Python dictionaries.

```python
def build_vtt_from_records(
    segments_list: list[dict],
    output_file: str,
    escape_text: bool = True,
    validate_segments: bool = True
) -> None
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `segments_list` | `list[dict]` | (required) | List of segment dictionaries |
| `output_file` | `str` | (required) | Output file path |
| `escape_text` | `bool` | `True` | Escape special characters (`&`, `<`, `>`) |
| `validate_segments` | `bool` | `True` | Validate segment data before writing |

**Segment Dictionary Schema:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `id` | `int` | No | Segment identifier (auto-generated if missing) |
| `start` | `float` | Yes | Start time in seconds |
| `end` | `float` | Yes | End time in seconds |
| `text` | `str` | Yes | Cue text content |

**Example:**

```python
from vtt_builder import build_vtt_from_records

segments = [
    {"start": 0.0, "end": 2.0, "text": "First cue"},
    {"start": 2.0, "end": 4.0, "text": "Tom & Jerry"},  # & will be escaped
    {"start": 4.0, "end": 6.0, "text": "Use <html> tags"},  # < > will be escaped
]

build_vtt_from_records(segments, "output.vtt")
```

**Output:**
```
WEBVTT

1
00:00:00.000 --> 00:00:02.000
First cue

2
00:00:02.000 --> 00:00:04.000
Tom &amp; Jerry

3
00:00:04.000 --> 00:00:06.000
Use &lt;html&gt; tags
```

**Raises:**

- `VttTimestampError`: Invalid timestamp (negative, end < start, overflow)
- `VttCueError`: Invalid cue content (empty text, contains `-->`)
- `IOError`: File system errors
- `KeyError`: Missing required fields
- `TypeError`: Invalid field types

---

### `build_vtt_from_json_files`

Build a WebVTT file from one or more JSON transcript files.

```python
def build_vtt_from_json_files(
    file_paths: list[str],
    output_file: str,
    escape_text: bool = True,
    validate_segments: bool = True
) -> None
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `file_paths` | `list[str]` | (required) | List of JSON file paths |
| `output_file` | `str` | (required) | Output VTT file path |
| `escape_text` | `bool` | `True` | Escape special characters |
| `validate_segments` | `bool` | `True` | Validate segment data |

**JSON File Schema:**

```json
{
  "transcript": "Full transcript text",
  "segments": [
    {
      "id": 1,
      "start": 0.0,
      "end": 2.5,
      "text": "Segment text"
    }
  ]
}
```

**Behavior:**
- Files are processed in order
- Timestamps are automatically offset to create continuous playback
- Each file's segments continue from where the previous file ended

**Example:**

```python
from vtt_builder import build_vtt_from_json_files

# Combine multiple transcript files
file_paths = [
    "part1.json",  # 0:00 - 5:00
    "part2.json",  # Offset to 5:00 - 10:00
    "part3.json",  # Offset to 10:00 - 15:00
]

build_vtt_from_json_files(file_paths, "combined.vtt")
```

**Raises:**
- `IOError`: File not found or read error
- `ValueError`: Invalid JSON format
- `VttTimestampError`: Invalid timestamps
- `VttCueError`: Invalid cue content

---

### `build_transcript_from_json_files`

Extract plain text transcripts from JSON files.

```python
def build_transcript_from_json_files(
    file_paths: list[str],
    output_file: str
) -> None
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `file_paths` | `list[str]` | List of JSON file paths |
| `output_file` | `str` | Output text file path |

**Behavior:**
- Extracts the `transcript` field from each JSON file
- Joins transcripts with blank lines
- Preserves original formatting (no escaping)

**Example:**

```python
from vtt_builder import build_transcript_from_json_files

build_transcript_from_json_files(
    ["part1.json", "part2.json"],
    "full_transcript.txt"
)
```

**Output:**
```
First file transcript text here.

Second file transcript text here.
```

---

## Validation Functions

### `validate_vtt_file`

Validate an existing WebVTT file for spec compliance.

```python
def validate_vtt_file(vtt_file: str) -> bool
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vtt_file` | `str` | Path to VTT file to validate |

**Returns:** `True` if file is valid

**Validation Checks:**

1. **Header**: Must start with "WEBVTT" (BOM allowed)
2. **Timestamps**: Both long (HH:MM:SS.mmm) and short (MM:SS.mmm) formats
3. **Cue structure**: Timing line followed by non-empty text
4. **Special blocks**: NOTE, STYLE, REGION blocks are skipped
5. **Cue settings**: Position, align, etc. are tolerated

**Example:**

```python
from vtt_builder import validate_vtt_file, VttHeaderError

try:
    validate_vtt_file("captions.vtt")
    print("File is valid!")
except VttHeaderError as e:
    print(f"Header error: {e}")
except VttTimestampError as e:
    print(f"Timestamp error: {e}")
except VttCueError as e:
    print(f"Cue error: {e}")
```

**Supported Features:**

✅ UTF-8 BOM at start of file
✅ Header text: `WEBVTT - Description`
✅ Metadata: `Kind: captions`
✅ Short timestamps: `00:05.000`
✅ Cue settings: `position:50% align:center`
✅ NOTE, STYLE, REGION blocks

---

### `validate_segments`

Validate segment data before building a VTT file.

```python
def validate_segments(segments_list: list[dict]) -> bool
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `segments_list` | `list[dict]` | List of segment dictionaries |

**Returns:** `True` if all segments are valid

**Validation Rules:**

| Rule | Error Type | Description |
|------|-----------|-------------|
| Non-negative start | `VttTimestampError` | `start >= 0` |
| Non-negative end | `VttTimestampError` | `end >= 0` |
| End after start | `VttTimestampError` | `end >= start` |
| Max timestamp | `VttTimestampError` | `<= 359999.999` (99:59:59.999) |
| Non-empty text | `VttCueError` | Text must have non-whitespace |
| No arrow substring | `VttCueError` | Cannot contain `-->` |

**Example:**

```python
from vtt_builder import validate_segments, VttTimestampError

segments = [
    {"start": 0.0, "end": 2.0, "text": "Valid"},
    {"start": 5.0, "end": 3.0, "text": "Invalid!"},  # end < start
]

try:
    validate_segments(segments)
except VttTimestampError as e:
    print(f"Validation failed: {e}")
    # Fix the segment and retry
```

---

## Utility Functions

### `escape_vtt_text`

Escape special characters for WebVTT cue text.

```python
def escape_vtt_text(text: str) -> str
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `text` | `str` | Text to escape |

**Returns:** Escaped text string

**Escape Mappings:**

| Character | Escape Sequence |
|-----------|-----------------|
| `&` | `&amp;` |
| `<` | `&lt;` |
| `>` | `&gt;` |

**Example:**

```python
from vtt_builder import escape_vtt_text

text = "Tom & Jerry say 1 < 2 > 0"
escaped = escape_vtt_text(text)
# Result: "Tom &amp; Jerry say 1 &lt; 2 &gt; 0"

# Important: --> substring is also escaped
text = "Arrow --> here"
escaped = escape_vtt_text(text)
# Result: "Arrow --&gt; here"
```

---

### `unescape_vtt_text`

Unescape WebVTT escape sequences back to original characters.

```python
def unescape_vtt_text(text: str) -> str
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `text` | `str` | Escaped text to unescape |

**Returns:** Original text with escape sequences converted

**Supported Sequences:**

| Escape Sequence | Character | Unicode |
|-----------------|-----------|---------|
| `&amp;` | `&` | U+0026 |
| `&lt;` | `<` | U+003C |
| `&gt;` | `>` | U+003E |
| `&nbsp;` | (non-breaking space) | U+00A0 |
| `&lrm;` | (left-to-right mark) | U+200E |
| `&rlm;` | (right-to-left mark) | U+200F |

**Example:**

```python
from vtt_builder import unescape_vtt_text

escaped = "Tom &amp; Jerry say 1 &lt; 2"
original = unescape_vtt_text(escaped)
# Result: "Tom & Jerry say 1 < 2"

# Special Unicode characters
text = "Hello&nbsp;World&lrm;"
unescaped = unescape_vtt_text(text)
# Result: "Hello World" (with non-breaking space and LTR mark)
```

---

## Exception Types

### Exception Hierarchy

```
ValueError (Python built-in)
└── VttError
    └── VttValidationError
        ├── VttTimestampError
        ├── VttHeaderError
        ├── VttCueError
        └── VttEscapingError
```

### `VttError`

Base exception for all VTT-related errors.

```python
from vtt_builder import VttError

try:
    # Any VTT operation
    pass
except VttError as e:
    print(f"VTT operation failed: {e}")
```

### `VttValidationError`

General validation errors.

```python
from vtt_builder import VttValidationError

try:
    validate_vtt_file("file.vtt")
except VttValidationError as e:
    print(f"Validation failed: {e}")
```

### `VttTimestampError`

Timestamp-specific validation errors.

**Common causes:**
- Negative timestamps
- End time before start time
- Invalid timestamp format
- Timestamp overflow (>99:59:59.999)

```python
from vtt_builder import VttTimestampError

try:
    validate_segments([{"start": -1, "end": 2, "text": "x"}])
except VttTimestampError as e:
    print(f"Invalid timestamp: {e}")
```

### `VttHeaderError`

WebVTT header validation errors.

**Common causes:**
- Missing "WEBVTT" signature
- Invalid header format (e.g., "WEBVTT-WRONG")

```python
from vtt_builder import VttHeaderError

try:
    validate_vtt_file("invalid.vtt")
except VttHeaderError as e:
    print(f"Invalid header: {e}")
```

### `VttCueError`

Cue content validation errors.

**Common causes:**
- Empty cue text
- Cue text contains "-->" substring
- Missing timing line after identifier

```python
from vtt_builder import VttCueError

try:
    validate_segments([{"start": 0, "end": 2, "text": "Arrow --> here"}])
except VttCueError as e:
    print(f"Invalid cue: {e}")
```

### `VttEscapingError`

Character escaping errors (reserved for future use).

---

## Data Formats

### Segment Dictionary

```python
segment = {
    "id": 1,           # Optional: Auto-generated if missing
    "start": 0.0,      # Required: Start time in seconds (float)
    "end": 2.5,        # Required: End time in seconds (float)
    "text": "Hello"    # Required: Cue text content (string)
}
```

### JSON Transcript File

```json
{
  "transcript": "Full plain text transcript",
  "segments": [
    {
      "id": 1,
      "start": 0.0,
      "end": 2.5,
      "text": "First segment"
    },
    {
      "id": 2,
      "start": 2.5,
      "end": 5.0,
      "text": "Second segment"
    }
  ]
}
```

### WebVTT Output Format

```
WEBVTT

1
00:00:00.000 --> 00:00:02.500
First segment

2
00:00:02.500 --> 00:00:05.000
Second segment
```

---

## Configuration Options

### Escaping Control

```python
# With escaping (default) - spec compliant
build_vtt_from_records(segments, "output.vtt", escape_text=True)

# Without escaping - use with caution
build_vtt_from_records(segments, "output.vtt", escape_text=False)
```

### Validation Control

```python
# With validation (default) - catches errors early
build_vtt_from_records(segments, "output.vtt", validate_segments=True)

# Without validation - faster but risky
build_vtt_from_records(segments, "output.vtt", validate_segments=False)
```

---

## Examples

### Basic Usage

```python
from vtt_builder import build_vtt_from_records

segments = [
    {"start": 0.0, "end": 2.0, "text": "Hello world"},
    {"start": 2.0, "end": 4.0, "text": "How are you?"},
]

build_vtt_from_records(segments, "captions.vtt")
```

### Handling Special Characters

```python
from vtt_builder import build_vtt_from_records, escape_vtt_text

# Characters are automatically escaped
segments = [
    {"start": 0.0, "end": 2.0, "text": "Tom & Jerry"},
    {"start": 2.0, "end": 4.0, "text": "<html> tags"},
]

build_vtt_from_records(segments, "output.vtt")
# Output contains: Tom &amp; Jerry
# Output contains: &lt;html&gt; tags

# Manual escaping for inspection
text = escape_vtt_text("Price: $10 < $20")
print(text)  # "Price: $10 &lt; $20"
```

### Pre-validation

```python
from vtt_builder import validate_segments, build_vtt_from_records, VttTimestampError

segments = load_segments_from_database()

try:
    validate_segments(segments)
    build_vtt_from_records(segments, "output.vtt", validate_segments=False)
except VttTimestampError as e:
    log.error(f"Data issue: {e}")
    fix_segments(segments)
```

### Multilingual Transcripts

```python
from vtt_builder import build_vtt_from_records

# Full Unicode support
segments = [
    {"start": 0.0, "end": 2.0, "text": "Español: ¿Cómo estás?"},
    {"start": 2.0, "end": 4.0, "text": "Français: Ça va bien"},
    {"start": 4.0, "end": 6.0, "text": "Deutsch: Größe und Übung"},
    {"start": 6.0, "end": 8.0, "text": "Polski: Łódź i Kraków"},
    {"start": 8.0, "end": 10.0, "text": "Português: São Paulo"},
    {"start": 10.0, "end": 12.0, "text": "Italiano: Città e università"},
]

build_vtt_from_records(segments, "multilingual.vtt")
```

### File Validation

```python
from vtt_builder import validate_vtt_file, VttHeaderError, VttTimestampError, VttCueError

def check_vtt_file(path):
    try:
        validate_vtt_file(path)
        return True, "Valid"
    except VttHeaderError as e:
        return False, f"Header issue: {e}"
    except VttTimestampError as e:
        return False, f"Timestamp issue: {e}"
    except VttCueError as e:
        return False, f"Cue issue: {e}"
    except FileNotFoundError:
        return False, "File not found"

valid, message = check_vtt_file("captions.vtt")
print(f"Validation result: {message}")
```

### Combining Multiple Transcript Files

```python
from vtt_builder import build_vtt_from_json_files

# Process a long video split into parts
parts = [f"part_{i}.json" for i in range(1, 11)]
build_vtt_from_json_files(parts, "full_video.vtt")

# Timestamps are automatically offset
# part_1.json: 0:00 - 10:00
# part_2.json: starts at 10:00
# etc.
```

### Error Handling Best Practices

```python
from vtt_builder import (
    build_vtt_from_records,
    VttError,
    VttTimestampError,
    VttCueError
)
import logging

def build_safe_vtt(segments, output_path):
    """Build VTT with comprehensive error handling."""
    try:
        build_vtt_from_records(segments, output_path)
        logging.info(f"Successfully created {output_path}")
        return True

    except VttTimestampError as e:
        logging.error(f"Timestamp validation failed: {e}")
        # Could attempt to fix timestamps here
        return False

    except VttCueError as e:
        logging.error(f"Cue content validation failed: {e}")
        # Could clean up text here
        return False

    except IOError as e:
        logging.error(f"File system error: {e}")
        return False

    except VttError as e:
        logging.error(f"Unexpected VTT error: {e}")
        return False

    except Exception as e:
        logging.critical(f"Unexpected error: {e}")
        raise
```

---

## Version History

- **0.3.0** (Current)
  - Added character escaping for WebVTT spec compliance
  - Added custom exception hierarchy
  - Added segment validation
  - Added UTF-8 BOM support
  - Added short timestamp format validation
  - Added `escape_vtt_text()` and `unescape_vtt_text()` utilities
  - Added `validate_segments()` function
  - Improved error messages

- **0.2.1**
  - Handle multiple newlines, tabs, and carriages
  - Update to uv package manager

- **0.2.0**
  - Handle notes and style blocks
  - Remove newlines when processing segments

- **0.1.0**
  - Initial release
  - Basic VTT generation from JSON and Python dicts
  - Basic validation
