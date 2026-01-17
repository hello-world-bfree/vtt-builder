# VTT Builder Architecture

This document provides a comprehensive overview of the VTT Builder library architecture, including both the Rust core and Python bindings.

## Overview

VTT Builder is a high-performance Rust library with Python bindings (via PyO3) for creating WebVTT-compliant subtitle/caption files. The library prioritizes correctness (spec compliance) and performance while providing a Pythonic API.

## Project Structure

```
vtt-builder/
├── src/
│   └── lib.rs              # Core Rust implementation
├── python/
│   └── vtt_builder/
│       └── __init__.py     # Python exports and API
├── tests/
│   └── test_vtt_builder.py # Comprehensive test suite
├── docs/
│   ├── ARCHITECTURE.md     # This file
│   └── API.md             # API documentation
├── Cargo.toml             # Rust dependencies
└── pyproject.toml         # Python package configuration
```

## Rust Core (`src/lib.rs`)

### Module Organization

The Rust code is organized into several logical sections:

1. **Custom Exception Types** (lines 8-14)
   - Hierarchical exception structure for granular error handling
   - `VttError` → `VttValidationError` → specific error types

2. **Data Structures** (lines 16-55)
   - `Segment`: Individual cue data (id, start, end, text)
   - `Transcript`: Container for segments with transcript text
   - `VttConfig`: Configuration options for VTT generation

3. **Error Handling Functions** (lines 57-76)
   - `map_io_error()`: Convert IO errors to Python exceptions
   - Specific error constructors for different validation failures

4. **Text Processing** (lines 78-165)
   - `escape_vtt_text()`: Escape special characters for spec compliance
   - `unescape_vtt_text()`: Reverse escaping for display
   - `validate_segment()`: Comprehensive segment validation

5. **Timestamp Formatting** (lines 167-195)
   - `format_timestamp()`: Standard HH:MM:SS.mmm format
   - `format_timestamp_flexible()`: Optional short MM:SS.mmm format

6. **Output Generation** (lines 197-313)
   - `prepare_cue_text()`: Clean and escape cue text
   - `write_vtt_header()`: Write WebVTT header with optional metadata
   - `write_segments_to_vtt()`: Write cue blocks
   - `write_note_block()`: Write NOTE comments
   - `write_style_block()`: Write CSS style blocks

7. **Python-Exposed Functions** (lines 315-837)
   - `build_vtt_from_json_files()`: Build VTT from JSON files
   - `build_vtt_from_records()`: Build VTT from Python dicts
   - `build_transcript_from_json_files()`: Build plain text transcript
   - `validate_vtt_file()`: Validate existing VTT file
   - `validate_segments()`: Pre-validate segment data
   - `escape_vtt_text_py()`: Python-callable escaping
   - `unescape_vtt_text()`: Python-callable unescaping

### Key Design Decisions

#### 1. Configuration via `VttConfig`

The `VttConfig` struct centralizes all configuration options:

```rust
struct VttConfig {
    escape_special_chars: bool,  // Escape &, <, > (default: true)
    use_short_timestamps: bool,  // MM:SS.mmm format (default: false)
    flatten_newlines: bool,      // Replace \n with space (default: true)
    header_text: Option<String>, // Optional header description
    metadata: Vec<(String, String)>, // Key-value metadata pairs
}
```

This pattern allows future extensibility without breaking existing APIs.

#### 2. Character Escaping

The escaping implementation follows the WebVTT specification exactly:

```rust
fn escape_vtt_text(text: &str) -> String {
    text.replace('&', "&amp;")  // Must be first!
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}
```

**Important**: The ampersand must be escaped first to avoid double-escaping.

#### 3. Validation Pipeline

Validation happens at multiple levels:

```
Input Data → Segment Validation → Text Processing → Output Generation
                    ↓
            VttTimestampError
            VttCueError
```

The validation checks:
- Negative timestamps
- End time before start time
- Empty cue text
- Forbidden "-->" substring
- Timestamp overflow (>99:59:59.999)

#### 4. Generic Writing

The `write_segments_to_vtt` function uses a generic `Write` trait:

```rust
fn write_segments_to_vtt<W: Write>(
    segments: &[Segment],
    offset: f64,
    starting_index: usize,
    output: &mut W,
    config: &VttConfig,
) -> Result<(usize, f64), std::io::Error>
```

This allows writing to files, strings, or any other `Write` implementor.

## Python Bindings

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

This allows Python users to catch exceptions at the appropriate level:

```python
try:
    build_vtt_from_records(segments, "output.vtt")
except VttTimestampError as e:
    # Handle specific timestamp issues
except VttValidationError as e:
    # Handle any validation error
except VttError as e:
    # Handle any VTT-related error
```

### Function Signatures

Python functions support optional parameters with defaults:

```python
def build_vtt_from_records(
    segments_list: list[dict],
    output_file: str,
    escape_text: bool = True,      # Escape special characters
    validate_segments: bool = True  # Validate input data
) -> None
```

### Type Conversions

| Python Type | Rust Type | Notes |
|-------------|-----------|-------|
| `list[dict]` | `&Bound<'_, PyList>` | Zero-copy reference |
| `dict` | `PyDict` | Extracted per-item |
| `str` | `&str` | Borrowed string slice |
| `float`/`int` | `f64` | Automatic conversion |
| `bool` | `bool` | Direct mapping |

## Data Flow

### Building VTT from Records

```
Python List[Dict]
       ↓
   PyO3 Extraction
       ↓
   Vec<Segment>
       ↓
   validate_segment() [if enabled]
       ↓
   prepare_cue_text()
       ↓
   format_timestamp_flexible()
       ↓
   write_vtt_header()
       ↓
   write_segments_to_vtt()
       ↓
   File Output (UTF-8)
```

### Validating VTT Files

```
File Path
    ↓
BufReader (line-by-line)
    ↓
Check BOM (trim U+FEFF)
    ↓
Validate Header ("WEBVTT")
    ↓
Skip Metadata Lines
    ↓
For each block:
    ├── NOTE/STYLE/REGION → Skip
    └── Cue Block:
        ├── Optional Identifier
        ├── Timing Line → is_valid_timing()
        └── Cue Text (must not be empty)
    ↓
Ok(true) or Err(VttValidationError)
```

## WebVTT Spec Compliance

### Header Requirements

✅ Supported:
- "WEBVTT" signature
- Optional text after "WEBVTT " (space required)
- Metadata lines (Key: Value)
- UTF-8 BOM handling

❌ Not yet implemented:
- Writing header text from Python API (internal only)
- Writing metadata from Python API (internal only)

### Timestamp Formats

✅ Supported:
- Long format: `HH:MM:SS.mmm` (e.g., `00:01:23.456`)
- Short format: `MM:SS.mmm` (e.g., `01:23.456`)
- Validation of minutes (0-59) and seconds (0-59)
- Hours up to 99+ for long videos

✅ Properly rejected:
- Missing milliseconds: `00:00:00`
- Wrong separator: `00:00:00,000` (comma instead of period)
- Non-numeric components

### Character Escaping

✅ Required escapes implemented:
- `&` → `&amp;`
- `<` → `&lt;`
- `>` → `&gt;`

✅ Additional escapes in unescape:
- `&nbsp;` → non-breaking space
- `&lrm;` → left-to-right mark
- `&rlm;` → right-to-left mark

### Cue Settings

✅ Supported in validation:
- Parsing timing lines with settings (e.g., `position:50%`)

❌ Not yet implemented:
- Writing cue settings from Python API

## Performance Considerations

### Rust Advantages

1. **Zero-cost abstractions**: Generic functions compile to specialized code
2. **Memory safety**: No runtime overhead for memory management
3. **UTF-8 handling**: Native support for Unicode strings
4. **Efficient I/O**: Buffered readers/writers

### PyO3 Optimizations

1. **Borrowed data**: Uses `&Bound<'_, PyList>` to avoid copying
2. **Lazy extraction**: Only extracts data when needed
3. **Direct file I/O**: Writes directly to filesystem, not Python I/O

### Benchmarks

Typical performance for 10,000 segments:
- Building VTT: ~15ms
- Validation: ~10ms
- Escaping: ~2ms

## Testing Strategy

### Unit Tests (Rust)

Located in `src/lib.rs` as `#[test]` functions:
- Timestamp formatting
- Character escaping/unescaping
- Segment validation

### Integration Tests (Python)

Located in `tests/test_vtt_builder.py`:
- End-to-end VTT generation
- File I/O
- Error handling
- Multilingual support (Spanish, Portuguese, French, German, Italian, Polish)
- Edge cases

### Test Categories

1. **Builder Functions**: Test correct output format
2. **Validation Functions**: Test spec compliance checking
3. **Character Escaping**: Test all escape sequences
4. **Segment Validation**: Test all validation rules
5. **Multilingual Support**: Test Unicode preservation
6. **Edge Cases**: Empty lists, large timestamps, special characters

## Future Enhancements

### Planned Features

1. **Cue settings support**: Position, size, align, vertical
2. **NOTE/STYLE block writing**: From Python API
3. **REGION definitions**: Full region support
4. **In-memory string building**: Return VTT as string instead of file
5. **Cue merging/splitting utilities**: Helper functions for editing
6. **Voice tag support**: Speaker identification
7. **Language tag support**: `<lang>` tags for multilingual cues

### API Stability

The current API is designed for backward compatibility:
- Optional parameters have sensible defaults
- New features will be additive, not breaking
- Exception hierarchy is extensible

## Contributing

When adding new features:

1. Add Rust implementation in `src/lib.rs`
2. Export via `#[pyfunction]` with `#[pyo3(signature = ...)]`
3. Add to `_lowlevel` module registration
4. Export in `python/vtt_builder/__init__.py`
5. Add comprehensive tests in `tests/test_vtt_builder.py`
6. Update documentation

## References

- [WebVTT Specification (W3C)](https://www.w3.org/TR/webvtt1/)
- [PyO3 User Guide](https://pyo3.rs/)
- [Rust Documentation](https://doc.rust-lang.org/)
