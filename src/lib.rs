use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use pyo3::{create_exception, exceptions::PyValueError};
use serde::Deserialize;
use std::fs::File;
use std::io::{BufRead, BufReader, Write};

// Custom exception hierarchy for better error handling in Python
create_exception!(vtt_builder, VttError, PyValueError);
create_exception!(vtt_builder, VttValidationError, VttError);
create_exception!(vtt_builder, VttTimestampError, VttValidationError);
create_exception!(vtt_builder, VttHeaderError, VttValidationError);
create_exception!(vtt_builder, VttCueError, VttValidationError);
create_exception!(vtt_builder, VttEscapingError, VttValidationError);
create_exception!(vtt_builder, VttSequenceError, VttValidationError);

// Maximum allowed timestamp in seconds (99:59:59.999)
const MAX_TIMESTAMP_SECONDS: f64 = 359999.999;

#[derive(Deserialize, Debug, Clone)]
struct Segment {
    id: u32,
    start: f64,
    end: f64,
    text: String,
}

#[derive(Deserialize, Debug)]
struct Transcript {
    transcript: String,
    segments: Vec<Segment>,
}

/// Configuration options for VTT generation
#[derive(Clone, Debug)]
struct VttConfig {
    /// Whether to escape special characters (recommended: true for spec compliance)
    escape_special_chars: bool,
    /// Whether to use short timestamp format (MM:SS.mmm) when hours = 0
    use_short_timestamps: bool,
    /// Whether to flatten newlines in cue text to spaces
    flatten_newlines: bool,
    /// Optional header text to append after "WEBVTT"
    header_text: Option<String>,
    /// Optional metadata key-value pairs (e.g., Kind: captions)
    metadata: Vec<(String, String)>,
}

impl Default for VttConfig {
    fn default() -> Self {
        VttConfig {
            escape_special_chars: true,
            use_short_timestamps: false,
            flatten_newlines: true,
            header_text: None,
            metadata: vec![],
        }
    }
}

fn map_io_error(e: std::io::Error) -> PyErr {
    pyo3::exceptions::PyIOError::new_err(e.to_string())
}

fn timestamp_error(msg: &str) -> PyErr {
    VttTimestampError::new_err(msg.to_string())
}

fn header_error(msg: &str) -> PyErr {
    VttHeaderError::new_err(msg.to_string())
}

fn cue_error(msg: &str) -> PyErr {
    VttCueError::new_err(msg.to_string())
}

fn sequence_error(msg: &str) -> PyErr {
    VttSequenceError::new_err(msg.to_string())
}

/// Quantizes a time in seconds to whole milliseconds.
///
/// Cue times are compared at millisecond precision because that is the precision
/// the WebVTT format serializes: a difference finer than one millisecond cannot
/// appear in the output file and cannot affect a player. Comparing raw f64 would
/// make exact abutment (`prev.end == next.start`) depend on the arithmetic that
/// produced each value, since floating-point absolute error scales with
/// magnitude.
///
/// Uses the same rounding as `format_timestamp_flexible`, so a value that writes
/// as `00:00:01.500` quantizes to `1500`.
fn to_millis(seconds: f64) -> u64 {
    (seconds * 1000.0).round() as u64
}

/// Helper function to extract segment data from a PyDict.
///
/// Extracts id, start, end, and text fields from a segment dictionary.
/// If id is missing, defaults to (idx + 1).
fn extract_segment_data(
    segment_dict: &Bound<'_, PyDict>,
    idx: usize,
) -> PyResult<(u32, f64, f64, String)> {
    let id: u32 = segment_dict
        .get_item("id")?
        .map(|v| v.extract().unwrap_or((idx + 1) as u32))
        .unwrap_or((idx + 1) as u32);

    let start: f64 = segment_dict
        .get_item("start")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
        .extract()
        .map_err(|_| {
            pyo3::exceptions::PyTypeError::new_err("'start' must be a number (int or float)")
        })?;

    let end: f64 = segment_dict
        .get_item("end")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
        .extract()
        .map_err(|_| {
            pyo3::exceptions::PyTypeError::new_err("'end' must be a number (int or float)")
        })?;

    let text: String = segment_dict
        .get_item("text")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'text' field"))?
        .extract()
        .map_err(|_| pyo3::exceptions::PyTypeError::new_err("'text' must be a string"))?;

    Ok((id, start, end, text))
}

/// Escapes special characters in text for WebVTT cue payload compliance.
///
/// According to the WebVTT specification, cue text cannot contain:
/// - The ampersand character (&) - must be escaped as &amp;
/// - The less-than sign (<) - must be escaped as &lt;
/// - The greater-than sign (>) - should be escaped as &gt;
/// - The substring "-->" - must be escaped (we escape the > to prevent this)
fn escape_vtt_text(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// Unescapes WebVTT escape sequences back to their original characters.
///
/// Supports all standard WebVTT escape sequences:
/// - &amp; -> &
/// - &lt; -> <
/// - &gt; -> >
/// - &nbsp; -> non-breaking space
/// - &lrm; -> left-to-right mark
/// - &rlm; -> right-to-left mark
#[pyfunction]
fn unescape_vtt_text(text: &str) -> String {
    text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", "\u{00A0}")
        .replace("&lrm;", "\u{200E}")
        .replace("&rlm;", "\u{200F}")
}

/// Validates a single segment for WebVTT compliance.
///
/// Checks:
/// - Timestamps are non-negative
/// - Start time <= End time
/// - Text is not empty (after trimming)
/// - Text doesn't contain forbidden "-->" substring
fn validate_segment(segment: &Segment) -> PyResult<()> {
    if segment.start < 0.0 {
        return Err(timestamp_error(&format!(
            "Segment {}: start time cannot be negative (got {})",
            segment.id, segment.start
        )));
    }

    if segment.end < 0.0 {
        return Err(timestamp_error(&format!(
            "Segment {}: end time cannot be negative (got {})",
            segment.id, segment.end
        )));
    }

    if segment.end < segment.start {
        return Err(timestamp_error(&format!(
            "Segment {}: end time ({}) must be >= start time ({})",
            segment.id, segment.end, segment.start
        )));
    }

    // Check for very large timestamps that could cause overflow
    if segment.start > MAX_TIMESTAMP_SECONDS || segment.end > MAX_TIMESTAMP_SECONDS {
        return Err(timestamp_error(&format!(
            "Segment {}: timestamp exceeds maximum allowed value (99:59:59.999)",
            segment.id
        )));
    }

    if segment.text.trim().is_empty() {
        return Err(cue_error(&format!(
            "Segment {}: cue text cannot be empty",
            segment.id
        )));
    }

    // Check for forbidden substring (before escaping)
    if segment.text.contains("-->") {
        return Err(cue_error(&format!(
            "Segment {}: cue text contains forbidden substring '-->'. \
             This will be escaped automatically, but you may want to review the content.",
            segment.id
        )));
    }

    Ok(())
}

/// Validates a cue list as an ordered sequence.
///
/// Operates on an already-extracted slice so both the public `validate_cue_sequence`
/// and the builders can call it without re-extracting dictionaries.
///
/// All comparisons are made on times quantized to whole milliseconds (see
/// `to_millis`). Error messages report the original unquantized times, so a
/// reader matching a log line against input data sees the values they passed in.
///
/// Checks, in order, for each adjacent pair:
/// - Zero-length cues (start == end after quantization)
/// - Out-of-order starts (start < previous start)
/// - Overlap (start < previous end); exact abutment is valid
/// - Minimum gap, when requested
/// - Media duration bounds, when requested
fn check_cue_sequence(
    segments: &[Segment],
    min_gap: Option<f64>,
    audio_duration: Option<f64>,
) -> PyResult<()> {
    let duration_bound = audio_duration.map(|d| (to_millis(d), d));
    let gap_bound = min_gap.map(|g| (to_millis(g), g));

    for (idx, segment) in segments.iter().enumerate() {
        let start_ms = to_millis(segment.start);
        let end_ms = to_millis(segment.end);

        if start_ms == end_ms {
            return Err(sequence_error(&format!(
                "Segment {} (index {}): cue has zero duration at millisecond \
                 precision (start {}, end {}); a zero-length cue is never displayed",
                segment.id, idx, segment.start, segment.end
            )));
        }

        if let Some((duration_ms, audio_duration)) = duration_bound {
            if start_ms >= duration_ms {
                return Err(sequence_error(&format!(
                    "Segment {} (index {}): cue starts at or after the media duration \
                     (start {}, duration {})",
                    segment.id, idx, segment.start, audio_duration
                )));
            }

            if end_ms > duration_ms {
                return Err(sequence_error(&format!(
                    "Segment {} (index {}): cue ends after the media duration \
                     (end {}, duration {}, overrun {})",
                    segment.id,
                    idx,
                    segment.end,
                    audio_duration,
                    segment.end - audio_duration
                )));
            }
        }

        if idx == 0 {
            continue;
        }

        let prev = &segments[idx - 1];
        let prev_start_ms = to_millis(prev.start);
        let prev_end_ms = to_millis(prev.end);

        if start_ms < prev_start_ms {
            return Err(sequence_error(&format!(
                "Segment {} (index {}): cue starts before the previous cue \
                 (segment {}, index {}) starts; cues are out of chronological order \
                 (start {}, previous start {})",
                segment.id,
                idx,
                prev.id,
                idx - 1,
                segment.start,
                prev.start
            )));
        }

        if start_ms < prev_end_ms {
            return Err(sequence_error(&format!(
                "Segment {} (index {}): cue overlaps the previous cue \
                 (segment {}, index {}); cue starts at {} but previous cue ends at {} \
                 (overlap {})",
                segment.id,
                idx,
                prev.id,
                idx - 1,
                segment.start,
                prev.end,
                prev.end - segment.start
            )));
        }

        if let Some((min_gap_ms, min_gap)) = gap_bound {
            let gap_ms = start_ms - prev_end_ms;
            if gap_ms < min_gap_ms {
                return Err(sequence_error(&format!(
                    "Segment {} (index {}): gap from the previous cue \
                     (segment {}, index {}) is {} seconds, less than the required \
                     minimum of {} seconds",
                    segment.id,
                    idx,
                    prev.id,
                    idx - 1,
                    segment.start - prev.end,
                    min_gap
                )));
            }
        }
    }

    Ok(())
}

/// Formats a timestamp with optional short format (MM:SS.mmm when hours = 0).
///
/// The WebVTT spec allows timestamps without hours component when the time
/// is less than one hour. This can make files more readable for short videos.
fn format_timestamp_flexible(seconds: f64, use_short_format: bool) -> String {
    let total_millis = (seconds * 1000.0).round() as u64;
    let hours = total_millis / 3_600_000;
    let minutes = (total_millis / 60_000) % 60;
    let secs = (total_millis / 1_000) % 60;
    let millis = total_millis % 1_000;

    if use_short_format && hours == 0 {
        format!("{:02}:{:02}.{:03}", minutes, secs, millis)
    } else {
        format!("{:02}:{:02}:{:02}.{:03}", hours, minutes, secs, millis)
    }
}

/// Cleans and prepares cue text for WebVTT output.
///
/// This function:
/// 1. Optionally flattens newlines, carriage returns, and tabs to spaces
/// 2. Normalizes whitespace (removes extra spaces)
/// 3. Optionally escapes special characters for spec compliance
fn prepare_cue_text(text: &str, config: &VttConfig) -> String {
    let mut clean_text = if config.flatten_newlines {
        text.replace(['\n', '\r', '\t'], " ")
            .split_whitespace()
            .collect::<Vec<&str>>()
            .join(" ")
    } else {
        text.trim().to_string()
    };

    if config.escape_special_chars {
        clean_text = escape_vtt_text(&clean_text);
    }

    clean_text
}

/// Writes the VTT header block to output.
///
/// The header includes:
/// - Required "WEBVTT" signature
/// - Optional header text (e.g., "WEBVTT - Video Captions")
/// - Optional metadata lines (e.g., "Kind: captions", "Language: en")
/// - Required blank line separator
fn write_vtt_header<W: Write>(output: &mut W, config: &VttConfig) -> Result<(), std::io::Error> {
    // Write WEBVTT signature with optional header text
    if let Some(ref header_text) = config.header_text {
        writeln!(output, "WEBVTT - {}", header_text)?;
    } else {
        writeln!(output, "WEBVTT")?;
    }

    // Write optional metadata
    for (key, value) in &config.metadata {
        writeln!(output, "{}: {}", key, value)?;
    }

    // Blank line to separate header from content
    writeln!(output)?;

    Ok(())
}

/// Writes segments to the VTT file, updating the index and offset.
///
/// This function handles:
/// - Text cleaning and escaping
/// - Timestamp formatting
/// - Cue identifier generation
/// - Proper VTT cue block formatting
fn write_segments_to_vtt<W: Write>(
    segments: &[Segment],
    offset: f64,
    starting_index: usize,
    output: &mut W,
    config: &VttConfig,
) -> Result<(usize, f64), std::io::Error> {
    let mut index = starting_index;

    for segment in segments {
        let start_time =
            format_timestamp_flexible(segment.start + offset, config.use_short_timestamps);
        let end_time = format_timestamp_flexible(segment.end + offset, config.use_short_timestamps);
        let clean_text = prepare_cue_text(&segment.text, config);

        writeln!(
            output,
            "{}\n{} --> {}\n{}\n",
            index, start_time, end_time, clean_text
        )?;
        index += 1;
    }

    let total_offset = if let Some(last_segment) = segments.last() {
        offset + last_segment.end
    } else {
        offset
    };

    Ok((index, total_offset))
}

/// Builds a VTT file from a list of JSON files.
///
/// This function reads transcript data from JSON files and generates a
/// spec-compliant WebVTT file with proper character escaping.
///
/// # Validation scope
/// This builder validates each cue on its own. It does **not** check cue
/// ordering, overlap, or gaps — not even within a single file. It reads the
/// input files one at a time and writes each before reading the next, advancing
/// a running time offset, so it never holds the whole cue list and cannot see
/// across a file boundary. A check that covered only within-file ordering would
/// imply a guarantee it cannot make, which is worse than no check: cross-file
/// boundaries are exactly where a bad offset shows up.
///
/// If you need the sequence guarantee, read the records yourself, concatenate
/// them, and call `build_vtt_from_records`, which validates the full sequence.
///
/// # Arguments
/// * `file_paths` - List of paths to JSON files containing transcript data
/// * `output_file` - Path where the VTT file will be written
///
/// # JSON Format
/// Each JSON file must contain:
/// ```json
/// {
///   "transcript": "Full text of the transcript",
///   "segments": [
///     {"id": 1, "start": 0.0, "end": 2.5, "text": "Segment text"}
///   ]
/// }
/// ```
#[pyfunction]
#[pyo3(signature = (file_paths, output_file, escape_text=true, validate_segments=true))]
fn build_vtt_from_json_files(
    file_paths: Vec<String>,
    output_file: &str,
    escape_text: bool,
    validate_segments: bool,
) -> PyResult<()> {
    let config = VttConfig {
        escape_special_chars: escape_text,
        ..Default::default()
    };

    let mut output = File::create(output_file).map_err(map_io_error)?;
    write_vtt_header(&mut output, &config).map_err(map_io_error)?;

    let mut total_offset = 0.0;
    let mut current_index = 1;

    for file_path in file_paths {
        let file = File::open(&file_path).map_err(map_io_error)?;
        let reader = BufReader::new(file);
        let transcript: Transcript = serde_json::from_reader(reader)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        // Validate segments if requested
        if validate_segments {
            for segment in &transcript.segments {
                validate_segment(segment)?;
            }
        }

        let (new_index, new_offset) = write_segments_to_vtt(
            &transcript.segments,
            total_offset,
            current_index,
            &mut output,
            &config,
        )
        .map_err(map_io_error)?;

        current_index = new_index;
        total_offset = new_offset;
    }

    Ok(())
}

#[pyfunction]
fn build_transcript_from_json_files(file_paths: Vec<String>, output_file: &str) -> PyResult<()> {
    let mut output = File::create(output_file).map_err(map_io_error)?;

    for (index, file_path) in file_paths.iter().enumerate() {
        let file = File::open(file_path).map_err(map_io_error)?;
        let reader = BufReader::new(file);
        let transcript: Transcript = serde_json::from_reader(reader)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        writeln!(output, "{}", transcript.transcript.trim()).map_err(map_io_error)?;

        if index < file_paths.len() - 1 {
            writeln!(output).map_err(map_io_error)?;
        }
    }

    Ok(())
}

/// Builds a sibling temporary path for an output file.
///
/// The temporary file lives in the same directory as the destination so the
/// final rename is same-filesystem and therefore atomic.
fn temp_path_for(output_file: &str) -> std::path::PathBuf {
    let path = std::path::Path::new(output_file);
    let file_name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "output.vtt".to_string());

    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);

    let temp_name = format!(".{}.{}.{}.tmp", file_name, std::process::id(), unique);

    match path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent.join(temp_name),
        _ => std::path::PathBuf::from(temp_name),
    }
}

/// Writes VTT content to a temporary sibling file and renames it into place.
///
/// Nothing appears at `output_file` until the content is complete, so a failed
/// build cannot leave a partial file where a caller would read it as a success,
/// and an existing file at the destination survives a failure untouched.
fn write_vtt_atomically(
    segments: &[Segment],
    output_file: &str,
    config: &VttConfig,
) -> PyResult<()> {
    let temp_path = temp_path_for(output_file);

    let write_result = (|| -> Result<(), std::io::Error> {
        let mut output = File::create(&temp_path)?;
        write_vtt_header(&mut output, config)?;
        write_segments_to_vtt(segments, 0.0, 1, &mut output, config)?;
        output.flush()?;
        Ok(())
    })();

    if let Err(e) = write_result {
        let _ = std::fs::remove_file(&temp_path);
        return Err(map_io_error(e));
    }

    if let Err(e) = std::fs::rename(&temp_path, output_file) {
        let _ = std::fs::remove_file(&temp_path);
        return Err(map_io_error(e));
    }

    Ok(())
}

/// Builds a VTT file from a list of Python dictionaries representing segments.
///
/// This is the most flexible way to create VTT files from Python, allowing
/// direct control over segment data.
///
/// When validation is enabled, every cue is validated on its own *and* the list
/// is validated as a sequence (ordering, overlap, zero-length cues), so a list
/// whose cues are individually valid but collectively malformed raises rather
/// than being written out. Validation completes before the destination is
/// touched, and content is written to a temporary sibling file and renamed into
/// place, so a rejected or failed build leaves no partial file behind and does
/// not disturb an existing file at the destination.
///
/// # Arguments
/// * `segments_list` - List of dictionaries with keys: id, start, end, text
/// * `output_file` - Path where the VTT file will be written
/// * `escape_text` - Whether to escape special characters (default: true)
/// * `validate_segments` - Whether to validate segment data (default: true).
///   Setting this to false skips both the per-cue and the sequence checks.
///
/// # Example
/// ```python
/// segments = [
///     {"id": 1, "start": 0.0, "end": 2.0, "text": "Hello world"},
///     {"id": 2, "start": 2.0, "end": 4.0, "text": "This is a test"}
/// ]
/// build_vtt_from_records(segments, "output.vtt")
/// ```
#[pyfunction]
#[pyo3(signature = (segments_list, output_file, escape_text=true, validate_segments=true))]
fn build_vtt_from_records(
    segments_list: &Bound<'_, PyList>,
    output_file: &str,
    escape_text: bool,
    validate_segments: bool,
) -> PyResult<()> {
    let config = VttConfig {
        escape_special_chars: escape_text,
        ..Default::default()
    };

    // Extract and validate everything before touching the destination, so a
    // rejected build cannot leave a truncated file behind.
    let segments = extract_segments(segments_list)?;

    if validate_segments {
        for segment in &segments {
            validate_segment(segment)?;
        }
        check_cue_sequence(&segments, None, None)?;
    }

    write_vtt_atomically(&segments, output_file, &config)
}

/// Validates a WebVTT file for spec compliance.
///
/// This function performs comprehensive validation including:
/// - Header format (with BOM support)
/// - Timestamp syntax (both short and long formats)
/// - Cue structure and content
/// - NOTE and STYLE block handling
///
/// # Arguments
/// * `vtt_file` - Path to the VTT file to validate
///
/// # Returns
/// * `Ok(true)` if the file is valid
/// * `Err(VttValidationError)` with specific error details if invalid
#[pyfunction]
fn validate_vtt_file(vtt_file: &str) -> PyResult<bool> {
    let file = File::open(vtt_file).map_err(map_io_error)?;
    let reader = BufReader::new(file);

    let mut lines = reader.lines();

    // Check for the "WEBVTT" header (with BOM support)
    if let Some(line_result) = lines.next() {
        let header = line_result.map_err(map_io_error)?;
        // Remove UTF-8 BOM if present (U+FEFF)
        let header = header.trim_start_matches('\u{FEFF}');
        let header_trimmed = header.trim();

        // Header must be "WEBVTT" optionally followed by space/tab and text
        if header_trimmed == "WEBVTT"
            || header_trimmed.starts_with("WEBVTT ")
            || header_trimmed.starts_with("WEBVTT\t")
        {
            // Valid header
        } else {
            return Err(header_error(&format!(
                "Invalid WEBVTT header. Must be 'WEBVTT' optionally followed by space/tab and text. Got: '{}'",
                header_trimmed
            )));
        }
    } else {
        return Err(header_error("Empty file"));
    }

    // Skip optional metadata headers until an empty line
    for line_result in &mut lines {
        let content = line_result.map_err(map_io_error)?;
        if content.trim().is_empty() {
            break;
        }
    }

    // Validate the cues
    while let Some(line_result) = lines.next() {
        let line = line_result.map_err(map_io_error)?;
        let line_trimmed = line.trim();

        if line_trimmed.is_empty() {
            continue;
        }

        // Check if this is a NOTE, STYLE, or REGION block (should be skipped)
        if line_trimmed.starts_with("NOTE")
            || line_trimmed.starts_with("STYLE")
            || line_trimmed.starts_with("REGION")
        {
            // Skip all lines until we find an empty line or EOF
            for block_line_result in &mut lines {
                let block_content = block_line_result.map_err(map_io_error)?;
                if block_content.trim().is_empty() {
                    break;
                }
            }
            continue;
        }

        // Cue identifiers are optional; They can be any text line not containing "-->"
        if !line_trimmed.contains("-->") {
            if let Some(next_result) = lines.next() {
                let next_line = next_result.map_err(map_io_error)?;
                let next_line_trimmed = next_line.trim();
                if !is_valid_timing(next_line_trimmed) {
                    let msg = format!(
                        "Invalid timing line after cue identifier '{}': '{}'",
                        line_trimmed, next_line_trimmed
                    );
                    return Err(timestamp_error(&msg));
                }
            } else {
                return Err(cue_error(&format!(
                    "Expected timing line after cue identifier '{}'",
                    line_trimmed
                )));
            }
        } else if !is_valid_timing(line_trimmed) {
            let msg = format!("Invalid timing line: '{}'", line_trimmed);
            return Err(timestamp_error(&msg));
        }

        let mut has_text = false;
        for cue_result in &mut lines {
            let content = cue_result.map_err(map_io_error)?;
            if content.trim().is_empty() {
                break;
            }
            has_text = true;
        }

        if !has_text {
            return Err(cue_error("Cue missing text content"));
        }
    }

    Ok(true)
}

fn parse_timestamp_to_seconds(timestamp: &str) -> Result<f64, String> {
    let parts: Vec<&str> = timestamp.split('.').collect();
    if parts.len() != 2 {
        return Err(format!(
            "Invalid timestamp format (missing milliseconds): '{}'",
            timestamp
        ));
    }

    let time_part = parts[0];
    let millis_str = parts[1];

    if millis_str.len() != 3 || !millis_str.chars().all(|c| c.is_ascii_digit()) {
        return Err(format!(
            "Milliseconds must be exactly 3 digits: '{}'",
            millis_str
        ));
    }

    let millis: f64 = millis_str
        .parse::<u32>()
        .map_err(|_| format!("Invalid milliseconds value: '{}'", millis_str))?
        as f64
        / 1000.0;

    let time_parts: Vec<&str> = time_part.split(':').collect();

    match time_parts.len() {
        2 => {
            let minutes: f64 = time_parts[0]
                .parse::<u32>()
                .map_err(|_| format!("Invalid minutes value: '{}'", time_parts[0]))?
                as f64;
            let secs: f64 = time_parts[1]
                .parse::<u32>()
                .map_err(|_| format!("Invalid seconds value: '{}'", time_parts[1]))?
                as f64;
            if secs >= 60.0 {
                return Err(format!("Seconds must be 0-59: '{}'", time_parts[1]));
            }
            Ok(minutes * 60.0 + secs + millis)
        }
        3 => {
            let hours: f64 = time_parts[0]
                .parse::<u32>()
                .map_err(|_| format!("Invalid hours value: '{}'", time_parts[0]))?
                as f64;
            let minutes: f64 = time_parts[1]
                .parse::<u32>()
                .map_err(|_| format!("Invalid minutes value: '{}'", time_parts[1]))?
                as f64;
            let secs: f64 = time_parts[2]
                .parse::<u32>()
                .map_err(|_| format!("Invalid seconds value: '{}'", time_parts[2]))?
                as f64;
            if minutes >= 60.0 {
                return Err(format!("Minutes must be 0-59: '{}'", time_parts[1]));
            }
            if secs >= 60.0 {
                return Err(format!("Seconds must be 0-59: '{}'", time_parts[2]));
            }
            Ok(hours * 3600.0 + minutes * 60.0 + secs + millis)
        }
        _ => Err(format!("Invalid timestamp format: '{}'", timestamp)),
    }
}

fn parse_timing_line(line: &str) -> Result<(f64, f64), String> {
    let parts: Vec<&str> = line.split("-->").collect();
    if parts.len() != 2 {
        return Err(format!("Invalid timing line: '{}'", line));
    }

    let start_str = parts[0].trim();
    let end_part = parts[1].trim();
    let end_str = end_part.split_whitespace().next().unwrap_or("");

    let start = parse_timestamp_to_seconds(start_str)?;
    let end = parse_timestamp_to_seconds(end_str)?;
    Ok((start, end))
}

fn parse_vtt_lines(
    lines: &mut impl Iterator<Item = Result<String, std::io::Error>>,
) -> PyResult<Vec<(f64, f64, String)>> {
    let header = lines
        .next()
        .ok_or_else(|| header_error("Empty file"))?
        .map_err(map_io_error)?;

    let header = header.trim_start_matches('\u{FEFF}');
    let header_trimmed = header.trim();

    if !(header_trimmed == "WEBVTT"
        || header_trimmed.starts_with("WEBVTT ")
        || header_trimmed.starts_with("WEBVTT\t"))
    {
        return Err(header_error(&format!(
            "Invalid WEBVTT header. Got: '{}'",
            header_trimmed
        )));
    }

    for line_result in &mut *lines {
        let content = line_result.map_err(map_io_error)?;
        if content.trim().is_empty() {
            break;
        }
    }

    let mut segments: Vec<(f64, f64, String)> = Vec::new();

    while let Some(line_result) = lines.next() {
        let line = line_result.map_err(map_io_error)?;
        let line_trimmed = line.trim();

        if line_trimmed.is_empty() {
            continue;
        }

        if line_trimmed.starts_with("NOTE")
            || line_trimmed.starts_with("STYLE")
            || line_trimmed.starts_with("REGION")
        {
            for block_line_result in &mut *lines {
                let block_content = block_line_result.map_err(map_io_error)?;
                if block_content.trim().is_empty() {
                    break;
                }
            }
            continue;
        }

        let timing_line = if !line_trimmed.contains("-->") {
            let next = lines
                .next()
                .ok_or_else(|| {
                    cue_error(&format!(
                        "Expected timing line after cue identifier '{}'",
                        line_trimmed
                    ))
                })?
                .map_err(map_io_error)?;
            next.trim().to_string()
        } else {
            line_trimmed.to_string()
        };

        let (start, end) = parse_timing_line(&timing_line).map_err(|e| timestamp_error(&e))?;

        let mut text_lines: Vec<String> = Vec::new();
        for cue_result in &mut *lines {
            let content = cue_result.map_err(map_io_error)?;
            if content.trim().is_empty() {
                break;
            }
            text_lines.push(content.trim().to_string());
        }

        if text_lines.is_empty() {
            return Err(cue_error("Cue missing text content"));
        }

        let text = text_lines.join("\n");
        segments.push((start, end, text));
    }

    Ok(segments)
}

/// Parses a WebVTT file and returns a list of segment dictionaries.
///
/// Each segment dict has keys: id (int), start (float), end (float), text (str).
/// Text is unescaped by default (e.g., &amp; becomes &).
///
/// # Arguments
/// * `vtt_file` - Path to the VTT file to parse
/// * `unescape` - Whether to unescape VTT entities in text (default: true)
#[pyfunction]
#[pyo3(signature = (vtt_file, unescape=true))]
fn parse_vtt_file(py: Python<'_>, vtt_file: &str, unescape: bool) -> PyResult<Py<PyList>> {
    let file = File::open(vtt_file).map_err(map_io_error)?;
    let reader = BufReader::new(file);
    let mut lines = reader.lines();

    let segments = parse_vtt_lines(&mut lines)?;
    segments_to_pylist(py, &segments, unescape)
}

/// Parses a WebVTT string and returns a list of segment dictionaries.
///
/// Each segment dict has keys: id (int), start (float), end (float), text (str).
/// Text is unescaped by default (e.g., &amp; becomes &).
///
/// # Arguments
/// * `vtt_content` - WebVTT content as a string
/// * `unescape` - Whether to unescape VTT entities in text (default: true)
#[pyfunction]
#[pyo3(signature = (vtt_content, unescape=true))]
fn parse_vtt_string(py: Python<'_>, vtt_content: &str, unescape: bool) -> PyResult<Py<PyList>> {
    let mut lines = vtt_content.lines().map(|l| Ok(l.to_string()));

    let segments = parse_vtt_lines(&mut lines)?;
    segments_to_pylist(py, &segments, unescape)
}

fn segments_to_pylist(
    py: Python<'_>,
    segments: &[(f64, f64, String)],
    unescape: bool,
) -> PyResult<Py<PyList>> {
    let result = PyList::empty(py);
    for (idx, (start, end, text)) in segments.iter().enumerate() {
        let dict = PyDict::new(py);
        dict.set_item("id", idx + 1)?;
        dict.set_item("start", start)?;
        dict.set_item("end", end)?;
        let final_text = if unescape {
            unescape_vtt_text(text)
        } else {
            text.clone()
        };
        dict.set_item("text", final_text)?;
        result.append(dict)?;
    }
    Ok(result.into())
}

/// Validates a WebVTT timing line (e.g., "00:00:00.000 --> 00:00:05.000").
///
/// Checks:
/// - Correct "-->" separator
/// - Valid timestamp format on both sides
/// - Optional cue settings after end timestamp
fn is_valid_timing(line: &str) -> bool {
    // The timing line should have the format "start_time --> end_time [settings]"
    let parts: Vec<&str> = line.split("-->").collect();
    if parts.len() != 2 {
        return false;
    }

    let start_time = parts[0].trim();

    // End time may have cue settings after it (e.g., "00:05.000 position:50%")
    let end_part = parts[1].trim();
    let end_time = end_part.split_whitespace().next().unwrap_or("");

    is_valid_timestamp(start_time) && is_valid_timestamp(end_time)
}

/// Validates a WebVTT timestamp format.
///
/// Supports both formats allowed by the spec:
/// - Short format: "MM:SS.mmm" (e.g., "00:05.000")
/// - Long format: "HH:MM:SS.mmm" (e.g., "00:00:05.000")
///
/// Also validates:
/// - Milliseconds must be exactly 3 digits
/// - Minutes must be 0-59
/// - Seconds must be 0-59
/// - All components must be numeric
fn is_valid_timestamp(timestamp: &str) -> bool {
    // Timestamp format: "MM:SS.mmm" or "HH:MM:SS.mmm"
    let parts: Vec<&str> = timestamp.split('.').collect();
    if parts.len() != 2 {
        return false;
    }

    let time_part = parts[0];
    let millis_part = parts[1];

    // Milliseconds must be exactly 3 digits
    if millis_part.len() != 3 || !millis_part.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }

    let time_parts: Vec<&str> = time_part.split(':').collect();

    // Support both MM:SS and HH:MM:SS formats
    match time_parts.len() {
        2 => {
            // MM:SS format
            let minutes = time_parts[0];
            let seconds = time_parts[1];

            // Minutes must be at least 2 digits
            if minutes.len() < 2 || !minutes.chars().all(|c| c.is_ascii_digit()) {
                return false;
            }

            // Seconds must be exactly 2 digits and 0-59
            if seconds.len() != 2 || !seconds.chars().all(|c| c.is_ascii_digit()) {
                return false;
            }

            if let Ok(sec_val) = seconds.parse::<u32>() {
                if sec_val > 59 {
                    return false;
                }
            } else {
                return false;
            }

            true
        }
        3 => {
            // HH:MM:SS format
            let hours = time_parts[0];
            let minutes = time_parts[1];
            let seconds = time_parts[2];

            // Hours must be at least 2 digits (can be more for long videos)
            if hours.len() < 2 || !hours.chars().all(|c| c.is_ascii_digit()) {
                return false;
            }

            // Minutes must be exactly 2 digits and 0-59
            if minutes.len() != 2 || !minutes.chars().all(|c| c.is_ascii_digit()) {
                return false;
            }

            if let Ok(min_val) = minutes.parse::<u32>() {
                if min_val > 59 {
                    return false;
                }
            } else {
                return false;
            }

            // Seconds must be exactly 2 digits and 0-59
            if seconds.len() != 2 || !seconds.chars().all(|c| c.is_ascii_digit()) {
                return false;
            }

            if let Ok(sec_val) = seconds.parse::<u32>() {
                if sec_val > 59 {
                    return false;
                }
            } else {
                return false;
            }

            true
        }
        _ => false,
    }
}

/// Escapes special characters for WebVTT cue text (Python-callable version).
///
/// According to the WebVTT specification, cue text cannot contain:
/// - & (ampersand) - escaped as &amp;
/// - < (less-than) - escaped as &lt;
/// - > (greater-than) - escaped as &gt;
///
/// # Arguments
/// * `text` - The text to escape
///
/// # Returns
/// * String with special characters escaped
///
/// # Example
/// ```python
/// from vtt_builder import escape_vtt_text
/// escaped = escape_vtt_text("Tom & Jerry say 1 < 2")
/// # Returns: "Tom &amp; Jerry say 1 &lt; 2"
/// ```
#[pyfunction]
fn escape_vtt_text_py(text: &str) -> String {
    escape_vtt_text(text)
}

/// Validates segment data without writing to a file.
///
/// This is useful for pre-validating data before attempting to build a VTT file.
///
/// Checks each segment on its own. It does **not** check a segment against its
/// neighbours, so an ordered-and-overlapping list passes here; use
/// `validate_cue_sequence` for ordering, overlap, gaps, and media-duration
/// bounds. In particular a zero-length cue (`start == end`) is accepted here and
/// rejected by `validate_cue_sequence`.
///
/// # Arguments
/// * `segments_list` - List of dictionaries with keys: id, start, end, text
///
/// # Returns
/// * `Ok(true)` if all segments are valid
/// * `Err` with specific validation error if any segment is invalid
#[pyfunction]
fn validate_segments(segments_list: &Bound<'_, PyList>) -> PyResult<bool> {
    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;
        let (id, start, end, text) = extract_segment_data(segment_dict, idx)?;

        let seg = Segment {
            id,
            start,
            end,
            text: text.trim().to_string(),
        };

        validate_segment(&seg)?;
    }

    Ok(true)
}

/// Extracts a whole Python segment list into a `Vec<Segment>`.
///
/// Shared by the functions that need the complete list before doing any work,
/// so cross-cue checks have something to look at.
fn extract_segments(segments_list: &Bound<'_, PyList>) -> PyResult<Vec<Segment>> {
    let mut segments = Vec::with_capacity(segments_list.len());

    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;
        let (id, start, end, text) = extract_segment_data(segment_dict, idx)?;

        segments.push(Segment {
            id,
            start,
            end,
            text: text.trim().to_string(),
        });
    }

    Ok(segments)
}

/// Validates a cue list as an ordered sequence.
///
/// Where `validate_segments` checks each cue on its own, this checks each cue
/// against its neighbours: ordering, overlap, an optional minimum gap, optional
/// media-duration bounds, and zero-length cues.
///
/// Comparisons are made at millisecond precision — the precision the WebVTT
/// format serializes — so two times that write identically compare as equal
/// regardless of the arithmetic that produced them. Exact abutment
/// (`previous end == next start`) is valid, since it is the normal output of a
/// well-behaved chunker; pass `min_gap` to require separation.
///
/// # Arguments
/// * `segments_list` - List of dictionaries with keys: id, start, end, text
/// * `min_gap` - Optional minimum gap in seconds required between adjacent cues
/// * `audio_duration` - Optional media duration in seconds bounding every cue
///
/// # Returns
/// * `Ok(true)` if the sequence is valid
/// * `Err(VttSequenceError)` naming both cues and the conflicting times
///
/// # Example
/// ```python
/// from vtt_builder import validate_cue_sequence
///
/// segments = [
///     {"start": 0.0, "end": 2.5, "text": "Hello"},
///     {"start": 2.5, "end": 5.0, "text": "World"},
/// ]
/// validate_cue_sequence(segments)  # True; exact abutment is valid
/// validate_cue_sequence(segments, min_gap=0.1)  # raises VttSequenceError
/// validate_cue_sequence(segments, audio_duration=4.0)  # raises VttSequenceError
/// ```
#[pyfunction]
#[pyo3(signature = (segments_list, min_gap=None, audio_duration=None))]
fn validate_cue_sequence(
    segments_list: &Bound<'_, PyList>,
    min_gap: Option<f64>,
    audio_duration: Option<f64>,
) -> PyResult<bool> {
    let segments = extract_segments(segments_list)?;
    check_cue_sequence(&segments, min_gap, audio_duration)?;
    Ok(true)
}

/// Bounds every cue in a list to lie within a media duration.
///
/// Lets a caller correct out-of-range cues rather than only detect them:
/// - A cue ending after `audio_duration` has its end truncated to it
/// - A cue starting at or after `audio_duration` is omitted
/// - Cues already within the duration are returned unchanged
///
/// Like the other transformations, the returned dictionaries carry exactly
/// `id`, `start`, `end`, and `text`; extra keys such as `speaker` or
/// `confidence` are not preserved. IDs are renumbered sequentially from 1.
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `audio_duration` - Media duration in seconds
///
/// # Returns
/// * List of segment dictionaries bounded to the duration
///
/// # Example
/// ```python
/// from vtt_builder import clamp_to_duration
///
/// segments = [
///     {"start": 0.0, "end": 2.5, "text": "Kept"},
///     {"start": 2.5, "end": 9.0, "text": "Truncated"},
///     {"start": 12.0, "end": 14.0, "text": "Dropped"},
/// ]
/// clamp_to_duration(segments, 5.0)
/// # [{"id": 1, "start": 0.0, "end": 2.5, ...},
/// #  {"id": 2, "start": 2.5, "end": 5.0, ...}]
/// ```
#[pyfunction]
fn clamp_to_duration(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    audio_duration: f64,
) -> PyResult<Py<PyList>> {
    let segments = extract_segments(segments_list)?;

    let result = PyList::empty(py);
    let mut next_id = 1u32;

    for segment in &segments {
        if segment.start >= audio_duration {
            continue;
        }

        let end = if segment.end > audio_duration {
            audio_duration
        } else {
            segment.end
        };

        let dict = PyDict::new(py);
        dict.set_item("id", next_id)?;
        dict.set_item("start", segment.start)?;
        dict.set_item("end", end)?;
        dict.set_item("text", &segment.text)?;
        result.append(dict)?;

        next_id += 1;
    }

    Ok(result.into())
}

/// Builds a VTT string from a list of Python dictionaries (in-memory, no file I/O).
///
/// This is useful for:
/// - Generating VTT content without writing to disk
/// - Testing and debugging
/// - Streaming or API responses
///
/// When validation is enabled, every cue is validated on its own *and* the list
/// is validated as a sequence (ordering, overlap, zero-length cues), so a list
/// whose cues are individually valid but collectively malformed raises rather
/// than being returned as content.
///
/// # Arguments
/// * `segments_list` - List of dictionaries with keys: id, start, end, text
/// * `escape_text` - Whether to escape special characters (default: true)
/// * `validate` - Whether to validate segment data (default: true). Setting this
///   to false skips both the per-cue and the sequence checks. Note this builder
///   names the flag `validate`, while the file builders name theirs
///   `validate_segments`.
///
/// # Returns
/// * String containing the complete VTT file content
/// * `Err(VttSequenceError)` if the cues are collectively malformed
#[pyfunction]
#[pyo3(signature = (segments_list, escape_text=true, validate=true))]
fn build_vtt_string(
    segments_list: &Bound<'_, PyList>,
    escape_text: bool,
    validate: bool,
) -> PyResult<String> {
    let config = VttConfig {
        escape_special_chars: escape_text,
        ..Default::default()
    };

    // Validate everything before producing any content, so a rejected build
    // returns an error rather than a partially built string.
    let segments = extract_segments(segments_list)?;

    if validate {
        for segment in &segments {
            validate_segment(segment)?;
        }
        check_cue_sequence(&segments, None, None)?;
    }

    let mut output = Vec::new();
    write_vtt_header(&mut output, &config)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    write_segments_to_vtt(&segments, 0.0, 1, &mut output, &config)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    String::from_utf8(output)
        .map_err(|e| pyo3::exceptions::PyUnicodeDecodeError::new_err(("utf-8", e.to_string())))
}

/// Merges consecutive segments with gaps smaller than the threshold.
///
/// This is useful for:
/// - Combining fragmented transcripts
/// - Reducing the number of cues
/// - Creating more readable captions
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `gap_threshold` - Maximum gap in seconds to merge (segments with gaps <= this are merged)
///
/// # Returns
/// * List of merged segment dictionaries
#[pyfunction]
#[pyo3(signature = (segments_list, gap_threshold=0.5))]
fn merge_segments(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    gap_threshold: f64,
) -> PyResult<Py<PyList>> {
    if segments_list.is_empty() {
        return Ok(PyList::empty(py).into());
    }

    let mut segments = Vec::new();

    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;
        let (id, start, end, text) = extract_segment_data(segment_dict, idx)?;

        segments.push(Segment {
            id,
            start,
            end,
            text: text.trim().to_string(),
        });
    }

    // Perform merging
    let mut merged = Vec::new();
    let mut current = segments[0].clone();

    for segment in &segments[1..] {
        if segment.start - current.end <= gap_threshold {
            // Merge: extend end time and concatenate text
            current.end = segment.end;
            current.text = format!("{} {}", current.text.trim(), segment.text.trim());
        } else {
            merged.push(current);
            current = segment.clone();
        }
    }
    merged.push(current);

    // Convert back to Python list
    let result = PyList::empty(py);
    for (idx, seg) in merged.iter().enumerate() {
        let dict = PyDict::new(py);
        dict.set_item("id", (idx + 1) as u32)?;
        dict.set_item("start", seg.start)?;
        dict.set_item("end", seg.end)?;
        dict.set_item("text", &seg.text)?;
        result.append(dict)?;
    }

    Ok(result.into())
}

/// Splits segments that exceed a maximum character length.
///
/// This is useful for:
/// - Ensuring readability of captions
/// - Meeting platform character limits
/// - Creating more digestible cue blocks
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `max_chars` - Maximum characters per segment
///
/// # Returns
/// * List of segment dictionaries with long segments split
#[pyfunction]
#[pyo3(signature = (segments_list, max_chars=80))]
fn split_long_segments(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    max_chars: usize,
) -> PyResult<Py<PyList>> {
    let result = PyList::empty(py);
    let mut new_id = 1u32;

    for segment in segments_list.iter() {
        let segment_dict = segment.downcast::<PyDict>()?;

        let start: f64 = segment_dict
            .get_item("start")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;

        let end: f64 = segment_dict
            .get_item("end")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;

        let text: String = segment_dict
            .get_item("text")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'text' field"))?
            .extract()?;

        let text = text.trim();

        if text.len() <= max_chars {
            // No need to split
            let dict = PyDict::new(py);
            dict.set_item("id", new_id)?;
            dict.set_item("start", start)?;
            dict.set_item("end", end)?;
            dict.set_item("text", text)?;
            result.append(dict)?;
            new_id += 1;
        } else {
            // Split the segment
            let words: Vec<&str> = text.split_whitespace().collect();
            let duration = end - start;
            let total_chars = text.len() as f64;

            let mut current_text = String::new();
            let mut current_start = start;

            for word in words {
                if !current_text.is_empty() && current_text.len() + word.len() + 1 > max_chars {
                    // Save current segment
                    let chars_in_segment = current_text.len() as f64;
                    let segment_duration = (chars_in_segment / total_chars) * duration;
                    let current_end = current_start + segment_duration;

                    let dict = PyDict::new(py);
                    dict.set_item("id", new_id)?;
                    dict.set_item("start", current_start)?;
                    dict.set_item("end", current_end)?;
                    dict.set_item("text", current_text.trim())?;
                    result.append(dict)?;
                    new_id += 1;

                    current_start = current_end;
                    current_text = word.to_string();
                } else {
                    if !current_text.is_empty() {
                        current_text.push(' ');
                    }
                    current_text.push_str(word);
                }
            }

            // Don't forget the last segment
            if !current_text.is_empty() {
                let dict = PyDict::new(py);
                dict.set_item("id", new_id)?;
                dict.set_item("start", current_start)?;
                dict.set_item("end", end)?;
                dict.set_item("text", current_text.trim())?;
                result.append(dict)?;
                new_id += 1;
            }
        }
    }

    Ok(result.into())
}

/// Formats seconds to a WebVTT timestamp string.
///
/// # Arguments
/// * `seconds` - Time in seconds (float)
/// * `use_short_format` - If true and hours=0, returns MM:SS.mmm format
///
/// # Returns
/// * Formatted timestamp string (e.g., "00:01:23.456" or "01:23.456")
#[pyfunction]
#[pyo3(signature = (seconds, use_short_format=false))]
fn seconds_to_timestamp(seconds: f64, use_short_format: bool) -> PyResult<String> {
    if seconds < 0.0 {
        return Err(timestamp_error("Seconds cannot be negative"));
    }
    if seconds > MAX_TIMESTAMP_SECONDS {
        return Err(timestamp_error(&format!(
            "Seconds exceeds maximum allowed value ({})",
            MAX_TIMESTAMP_SECONDS
        )));
    }
    Ok(format_timestamp_flexible(seconds, use_short_format))
}

/// Parses a WebVTT timestamp string to seconds.
///
/// Supports both formats:
/// - Long: "HH:MM:SS.mmm" (e.g., "01:23:45.678")
/// - Short: "MM:SS.mmm" (e.g., "23:45.678")
///
/// # Arguments
/// * `timestamp` - Timestamp string to parse
///
/// # Returns
/// * Time in seconds as float
#[pyfunction]
fn timestamp_to_seconds(timestamp: &str) -> PyResult<f64> {
    let parts: Vec<&str> = timestamp.split('.').collect();
    if parts.len() != 2 {
        return Err(timestamp_error(&format!(
            "Invalid timestamp format (missing milliseconds): '{}'",
            timestamp
        )));
    }

    let time_part = parts[0];
    let millis_str = parts[1];

    if millis_str.len() != 3 {
        return Err(timestamp_error(&format!(
            "Milliseconds must be exactly 3 digits: '{}'",
            millis_str
        )));
    }

    let millis: f64 = millis_str
        .parse::<u32>()
        .map_err(|_| timestamp_error(&format!("Invalid milliseconds value: '{}'", millis_str)))?
        as f64
        / 1000.0;

    let time_parts: Vec<&str> = time_part.split(':').collect();

    let seconds = match time_parts.len() {
        2 => {
            // MM:SS format
            let minutes: f64 = time_parts[0].parse::<u32>().map_err(|_| {
                timestamp_error(&format!("Invalid minutes value: '{}'", time_parts[0]))
            })? as f64;
            let secs: f64 = time_parts[1].parse::<u32>().map_err(|_| {
                timestamp_error(&format!("Invalid seconds value: '{}'", time_parts[1]))
            })? as f64;

            if secs >= 60.0 {
                return Err(timestamp_error(&format!(
                    "Seconds must be 0-59: '{}'",
                    time_parts[1]
                )));
            }

            minutes * 60.0 + secs + millis
        }
        3 => {
            // HH:MM:SS format
            let hours: f64 = time_parts[0].parse::<u32>().map_err(|_| {
                timestamp_error(&format!("Invalid hours value: '{}'", time_parts[0]))
            })? as f64;
            let minutes: f64 = time_parts[1].parse::<u32>().map_err(|_| {
                timestamp_error(&format!("Invalid minutes value: '{}'", time_parts[1]))
            })? as f64;
            let secs: f64 = time_parts[2].parse::<u32>().map_err(|_| {
                timestamp_error(&format!("Invalid seconds value: '{}'", time_parts[2]))
            })? as f64;

            if minutes >= 60.0 {
                return Err(timestamp_error(&format!(
                    "Minutes must be 0-59: '{}'",
                    time_parts[1]
                )));
            }
            if secs >= 60.0 {
                return Err(timestamp_error(&format!(
                    "Seconds must be 0-59: '{}'",
                    time_parts[2]
                )));
            }

            hours * 3600.0 + minutes * 60.0 + secs + millis
        }
        _ => {
            return Err(timestamp_error(&format!(
                "Invalid timestamp format: '{}'",
                timestamp
            )))
        }
    };

    Ok(seconds)
}

/// Calculates statistics for a list of segments.
///
/// Returns a dictionary with:
/// - total_duration: Total duration in seconds
/// - num_segments: Number of segments
/// - avg_duration: Average segment duration
/// - total_words: Total word count
/// - total_chars: Total character count (excluding whitespace normalization)
/// - avg_words_per_segment: Average words per segment
/// - avg_chars_per_segment: Average characters per segment
/// - words_per_second: Speaking rate (words per second)
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
///
/// # Returns
/// * Dictionary with statistics
#[pyfunction]
fn get_segments_stats(py: Python<'_>, segments_list: &Bound<'_, PyList>) -> PyResult<Py<PyDict>> {
    let stats = PyDict::new(py);

    if segments_list.is_empty() {
        stats.set_item("total_duration", 0.0)?;
        stats.set_item("num_segments", 0)?;
        stats.set_item("avg_duration", 0.0)?;
        stats.set_item("total_words", 0)?;
        stats.set_item("total_chars", 0)?;
        stats.set_item("avg_words_per_segment", 0.0)?;
        stats.set_item("avg_chars_per_segment", 0.0)?;
        stats.set_item("words_per_second", 0.0)?;
        return Ok(stats.into());
    }

    let mut total_duration = 0.0f64;
    let mut total_words = 0usize;
    let mut total_chars = 0usize;
    let num_segments = segments_list.len();

    for segment in segments_list.iter() {
        let segment_dict = segment.downcast::<PyDict>()?;

        let start: f64 = segment_dict
            .get_item("start")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;

        let end: f64 = segment_dict
            .get_item("end")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;

        let text: String = segment_dict
            .get_item("text")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'text' field"))?
            .extract()?;

        total_duration += end - start;
        total_words += text.split_whitespace().count();
        total_chars += text.trim().len();
    }

    let avg_duration = total_duration / num_segments as f64;
    let avg_words = total_words as f64 / num_segments as f64;
    let avg_chars = total_chars as f64 / num_segments as f64;
    let words_per_second = if total_duration > 0.0 {
        total_words as f64 / total_duration
    } else {
        0.0
    };

    stats.set_item("total_duration", total_duration)?;
    stats.set_item("num_segments", num_segments)?;
    stats.set_item("avg_duration", avg_duration)?;
    stats.set_item("total_words", total_words)?;
    stats.set_item("total_chars", total_chars)?;
    stats.set_item("avg_words_per_segment", avg_words)?;
    stats.set_item("avg_chars_per_segment", avg_chars)?;
    stats.set_item("words_per_second", words_per_second)?;

    Ok(stats.into())
}

/// Shifts all segment timestamps by a given offset.
///
/// Useful for:
/// - Synchronizing transcripts with video
/// - Adjusting timing for different versions
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `offset_seconds` - Time offset in seconds (can be negative)
///
/// # Returns
/// * List of segments with adjusted timestamps
#[pyfunction]
fn shift_timestamps(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    offset_seconds: f64,
) -> PyResult<Py<PyList>> {
    let result = PyList::empty(py);

    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;
        let (id, start, end, text) = extract_segment_data(segment_dict, idx)?;

        let new_start = start + offset_seconds;
        let new_end = end + offset_seconds;

        if new_start < 0.0 || new_end < 0.0 {
            return Err(timestamp_error(&format!(
                "Segment {}: shifting by {} would result in negative timestamp",
                id, offset_seconds
            )));
        }

        let dict = PyDict::new(py);
        dict.set_item("id", id)?;
        dict.set_item("start", new_start)?;
        dict.set_item("end", new_end)?;
        dict.set_item("text", text.trim())?;
        result.append(dict)?;
    }

    Ok(result.into())
}

/// Filters segments to only include those within a time range.
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `start_time` - Start of time range (inclusive)
/// * `end_time` - End of time range (inclusive)
///
/// # Returns
/// * List of segments that overlap with the time range
#[pyfunction]
#[pyo3(signature = (segments_list, start_time, end_time))]
fn filter_segments_by_time(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    start_time: f64,
    end_time: f64,
) -> PyResult<Py<PyList>> {
    let result = PyList::empty(py);

    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;

        let seg_start: f64 = segment_dict
            .get_item("start")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;

        let seg_end: f64 = segment_dict
            .get_item("end")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;

        // Include segment if it overlaps with the range
        if seg_end >= start_time && seg_start <= end_time {
            let id: u32 = segment_dict
                .get_item("id")?
                .map(|v| v.extract().unwrap_or((idx + 1) as u32))
                .unwrap_or((idx + 1) as u32);

            let text: String = segment_dict
                .get_item("text")?
                .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'text' field"))?
                .extract()?;

            let dict = PyDict::new(py);
            dict.set_item("id", id)?;
            dict.set_item("start", seg_start)?;
            dict.set_item("end", seg_end)?;
            dict.set_item("text", text.trim())?;
            result.append(dict)?;
        }
    }

    Ok(result.into())
}

// ============================================================================
// Podcast Processing Functions
// ============================================================================

/// Removes common filler words from segment text.
///
/// Useful for cleaning up podcast transcriptions where speakers use verbal
/// fillers like "um", "uh", "like", "you know", etc.
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `fillers` - Optional list of filler words to remove (uses defaults if not provided)
/// * `preserve_timing` - If true, removes fillers but keeps original timing
///
/// # Returns
/// * List of segments with filler words removed
#[pyfunction]
#[pyo3(signature = (segments_list, fillers=None, preserve_timing=true))]
fn remove_filler_words(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    fillers: Option<Vec<String>>,
    preserve_timing: bool,
) -> PyResult<Py<PyList>> {
    let default_fillers = vec![
        "um",
        "uh",
        "uhh",
        "umm",
        "er",
        "err",
        "ah",
        "ahh",
        "eh",
        "like",
        "you know",
        "i mean",
        "sort of",
        "kind of",
        "basically",
        "actually",
        "literally",
        "right",
        "okay so",
        "so like",
    ];

    let filler_list: Vec<String> =
        fillers.unwrap_or_else(|| default_fillers.iter().map(|s| s.to_string()).collect());

    // Pre-compile all regex patterns once for better performance
    let compiled_filters: Vec<regex::Regex> = filler_list
        .iter()
        .filter_map(|filler| {
            let pattern = format!(r"(?i)\b{}\b", regex::escape(filler));
            regex::Regex::new(&pattern).ok()
        })
        .collect();

    let result = PyList::empty(py);

    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;
        let (id, start, end, text) = extract_segment_data(segment_dict, idx)?;

        // Remove filler words using pre-compiled regexes
        let mut cleaned_text = text.clone();
        for re in &compiled_filters {
            cleaned_text = re.replace_all(&cleaned_text, "").to_string();
        }

        // Clean up multiple spaces
        let cleaned_text = cleaned_text
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");

        // Skip empty segments unless preserving timing
        if cleaned_text.is_empty() && !preserve_timing {
            continue;
        }

        let dict = PyDict::new(py);
        dict.set_item(
            "id",
            if preserve_timing {
                id
            } else {
                (result.len() + 1) as u32
            },
        )?;
        dict.set_item("start", start)?;
        dict.set_item("end", end)?;
        dict.set_item("text", cleaned_text)?;

        // Preserve speaker info if present
        if let Ok(Some(speaker)) = segment_dict.get_item("speaker") {
            dict.set_item("speaker", speaker)?;
        }

        result.append(dict)?;
    }

    Ok(result.into())
}

/// Groups segments by speaker for podcast transcriptions with speaker diarization.
///
/// Takes segments with speaker labels and groups consecutive segments by the same
/// speaker into single cues.
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries with 'speaker' field
/// * `max_gap` - Maximum gap (seconds) to merge same-speaker segments (default 2.0)
/// * `format_speaker` - If true, prepends speaker name to text (default true)
///
/// # Returns
/// * List of grouped segments with speaker information
#[pyfunction]
#[pyo3(signature = (segments_list, max_gap=2.0, format_speaker=true))]
fn group_by_speaker(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    max_gap: f64,
    format_speaker: bool,
) -> PyResult<Py<PyList>> {
    if segments_list.is_empty() {
        return Ok(PyList::empty(py).into());
    }

    let result = PyList::empty(py);
    let mut current_speaker: Option<String> = None;
    let mut current_start = 0.0f64;
    let mut current_end = 0.0f64;
    let mut current_texts: Vec<String> = vec![];

    for segment in segments_list.iter() {
        let segment_dict = segment.downcast::<PyDict>()?;

        let start: f64 = segment_dict
            .get_item("start")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;

        let end: f64 = segment_dict
            .get_item("end")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;

        let text: String = segment_dict
            .get_item("text")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'text' field"))?
            .extract()?;

        let speaker: String = segment_dict
            .get_item("speaker")?
            .map(|v| v.extract().unwrap_or_else(|_| "Unknown".to_string()))
            .unwrap_or_else(|| "Unknown".to_string());

        let should_merge =
            current_speaker.as_ref() == Some(&speaker) && (start - current_end) <= max_gap;

        if should_merge {
            // Continue accumulating for same speaker
            current_end = end;
            current_texts.push(text);
        } else {
            // Output previous speaker's segment (if any)
            if !current_texts.is_empty() {
                let dict = PyDict::new(py);
                dict.set_item("id", (result.len() + 1) as u32)?;
                dict.set_item("start", current_start)?;
                dict.set_item("end", current_end)?;

                let combined_text = current_texts.join(" ");
                if format_speaker {
                    if let Some(ref spk) = current_speaker {
                        dict.set_item("text", format!("<v {}>{}", spk, combined_text))?;
                    } else {
                        dict.set_item("text", combined_text)?;
                    }
                } else {
                    dict.set_item("text", combined_text)?;
                }

                if let Some(ref spk) = current_speaker {
                    dict.set_item("speaker", spk.clone())?;
                }

                result.append(dict)?;
            }

            // Start new speaker segment
            current_speaker = Some(speaker);
            current_start = start;
            current_end = end;
            current_texts = vec![text];
        }
    }

    // Output final segment
    if !current_texts.is_empty() {
        let dict = PyDict::new(py);
        dict.set_item("id", (result.len() + 1) as u32)?;
        dict.set_item("start", current_start)?;
        dict.set_item("end", current_end)?;

        let combined_text = current_texts.join(" ");
        if format_speaker {
            if let Some(ref spk) = current_speaker {
                dict.set_item("text", format!("<v {}>{}", spk, combined_text))?;
            } else {
                dict.set_item("text", combined_text)?;
            }
        } else {
            dict.set_item("text", combined_text)?;
        }

        if let Some(ref spk) = current_speaker {
            dict.set_item("speaker", spk.clone())?;
        }

        result.append(dict)?;
    }

    Ok(result.into())
}

/// Filters segments based on confidence scores.
///
/// Useful for cleaning up transcriptions by removing low-confidence segments
/// that are likely to contain errors.
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries with optional 'confidence' field
/// * `min_confidence` - Minimum confidence threshold (0.0 to 1.0, default 0.8)
/// * `remove_or_mark` - "remove" to delete low-confidence segments, "mark" to add flag
///
/// # Returns
/// * List of segments meeting confidence threshold
#[pyfunction]
#[pyo3(signature = (segments_list, min_confidence=0.8, remove_or_mark="remove"))]
fn filter_by_confidence(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    min_confidence: f64,
    remove_or_mark: &str,
) -> PyResult<Py<PyList>> {
    let result = PyList::empty(py);
    let should_remove = remove_or_mark == "remove";

    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;

        let confidence: f64 = segment_dict
            .get_item("confidence")?
            .map(|v| v.extract().unwrap_or(1.0))
            .unwrap_or(1.0); // Assume high confidence if not provided

        let id: u32 = segment_dict
            .get_item("id")?
            .map(|v| v.extract().unwrap_or((idx + 1) as u32))
            .unwrap_or((idx + 1) as u32);

        let start: f64 = segment_dict
            .get_item("start")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;

        let end: f64 = segment_dict
            .get_item("end")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;

        let text: String = segment_dict
            .get_item("text")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'text' field"))?
            .extract()?;

        if should_remove && confidence < min_confidence {
            continue;
        }

        let dict = PyDict::new(py);
        dict.set_item(
            "id",
            if should_remove {
                (result.len() + 1) as u32
            } else {
                id
            },
        )?;
        dict.set_item("start", start)?;
        dict.set_item("end", end)?;
        dict.set_item("text", text)?;
        dict.set_item("confidence", confidence)?;

        if !should_remove && confidence < min_confidence {
            dict.set_item("low_confidence", true)?;
        }

        // Preserve speaker info if present
        if let Ok(Some(speaker)) = segment_dict.get_item("speaker") {
            dict.set_item("speaker", speaker)?;
        }

        result.append(dict)?;
    }

    Ok(result.into())
}

/// Aggregates word-level timing data into sentence-like segments.
///
/// Many transcription APIs return word-level timestamps. This function groups
/// words into natural sentence boundaries based on punctuation and pauses.
///
/// # Arguments
/// * `words_list` - List of word dictionaries with 'word', 'start', 'end' fields
/// * `max_segment_duration` - Maximum duration for a single segment (default 10.0s)
/// * `pause_threshold` - Pause duration that forces segment break (default 1.0s)
///
/// # Returns
/// * List of segment dictionaries
#[pyfunction]
#[pyo3(signature = (words_list, max_segment_duration=10.0, pause_threshold=1.0))]
fn words_to_segments(
    py: Python<'_>,
    words_list: &Bound<'_, PyList>,
    max_segment_duration: f64,
    pause_threshold: f64,
) -> PyResult<Py<PyList>> {
    if words_list.is_empty() {
        return Ok(PyList::empty(py).into());
    }

    let result = PyList::empty(py);
    let mut segment_words: Vec<String> = vec![];
    let mut segment_start = 0.0f64;
    let mut segment_end = 0.0f64;
    let mut last_end = 0.0f64;

    for word_item in words_list.iter() {
        let word_dict = word_item.downcast::<PyDict>()?;

        let word: String = word_dict
            .get_item("word")?
            .or_else(|| word_dict.get_item("text").ok().flatten())
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'word' or 'text' field"))?
            .extract()?;

        let word_start: f64 = word_dict
            .get_item("start")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;

        let word_end: f64 = word_dict
            .get_item("end")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;

        let pause = if segment_words.is_empty() {
            0.0
        } else {
            word_start - last_end
        };

        let current_duration = if segment_words.is_empty() {
            0.0
        } else {
            word_end - segment_start
        };

        // Check if we should start a new segment
        let should_break = !segment_words.is_empty()
            && (pause >= pause_threshold
                || current_duration > max_segment_duration
                || word.ends_with('.')
                || word.ends_with('?')
                || word.ends_with('!'));

        // If the last word had sentence-ending punctuation, break after it
        let last_word_ends_sentence = segment_words
            .last()
            .map(|w| w.ends_with('.') || w.ends_with('?') || w.ends_with('!'))
            .unwrap_or(false);

        if should_break || (last_word_ends_sentence && !segment_words.is_empty()) {
            // Save current segment
            let dict = PyDict::new(py);
            dict.set_item("id", (result.len() + 1) as u32)?;
            dict.set_item("start", segment_start)?;
            dict.set_item("end", segment_end)?;
            dict.set_item("text", segment_words.join(" "))?;
            result.append(dict)?;

            // Start new segment
            segment_words = vec![word];
            segment_start = word_start;
            segment_end = word_end;
        } else if segment_words.is_empty() {
            // First word
            segment_words.push(word);
            segment_start = word_start;
            segment_end = word_end;
        } else {
            // Continue current segment
            segment_words.push(word);
            segment_end = word_end;
        }

        last_end = word_end;
    }

    // Output final segment
    if !segment_words.is_empty() {
        let dict = PyDict::new(py);
        dict.set_item("id", (result.len() + 1) as u32)?;
        dict.set_item("start", segment_start)?;
        dict.set_item("end", segment_end)?;
        dict.set_item("text", segment_words.join(" "))?;
        result.append(dict)?;
    }

    Ok(result.into())
}

/// Detects and removes repeated phrases that often occur in podcast transcriptions.
///
/// When speakers stutter or repeat themselves, transcription services may include
/// duplicate phrases. This function identifies and removes such repetitions.
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `min_repetitions` - Minimum number of immediate repetitions to detect (default 2)
/// * `max_phrase_words` - Maximum words in a phrase to check for repetition (default 5)
///
/// # Returns
/// * List of segments with repeated phrases removed
#[pyfunction]
#[pyo3(signature = (segments_list, min_repetitions=2, max_phrase_words=5))]
fn remove_repeated_phrases(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    min_repetitions: usize,
    max_phrase_words: usize,
) -> PyResult<Py<PyList>> {
    let result = PyList::empty(py);

    for (idx, segment) in segments_list.iter().enumerate() {
        let segment_dict = segment.downcast::<PyDict>()?;
        let (id, start, end, text) = extract_segment_data(segment_dict, idx)?;

        // Remove repeated phrases
        let words: Vec<&str> = text.split_whitespace().collect();
        let mut cleaned_words: Vec<String> = vec![];
        let mut i = 0;

        while i < words.len() {
            let mut found_repetition = false;

            // Check for repeated phrases of different lengths
            for phrase_len in (1..=max_phrase_words).rev() {
                if i + phrase_len * min_repetitions > words.len() {
                    continue;
                }

                let phrase: Vec<&str> = words[i..i + phrase_len].to_vec();
                let mut repetition_count = 1;

                // Count consecutive repetitions
                let mut j = i + phrase_len;
                while j + phrase_len <= words.len() {
                    let next_phrase: Vec<&str> = words[j..j + phrase_len].to_vec();
                    if phrase
                        .iter()
                        .zip(next_phrase.iter())
                        .all(|(a, b)| a.to_lowercase() == b.to_lowercase())
                    {
                        repetition_count += 1;
                        j += phrase_len;
                    } else {
                        break;
                    }
                }

                if repetition_count >= min_repetitions {
                    // Keep only one instance of the repeated phrase
                    for word in phrase {
                        cleaned_words.push(word.to_string());
                    }
                    i = j;
                    found_repetition = true;
                    break;
                }
            }

            if !found_repetition {
                cleaned_words.push(words[i].to_string());
                i += 1;
            }
        }

        let dict = PyDict::new(py);
        dict.set_item("id", id)?;
        dict.set_item("start", start)?;
        dict.set_item("end", end)?;
        dict.set_item("text", cleaned_words.join(" "))?;

        // Preserve speaker info if present
        if let Ok(Some(speaker)) = segment_dict.get_item("speaker") {
            dict.set_item("speaker", speaker)?;
        }

        result.append(dict)?;
    }

    Ok(result.into())
}

/// Adds chapter markers/timestamps for podcast navigation.
///
/// Identifies potential chapter breaks based on long pauses, topic changes,
/// or explicit markers in the text.
///
/// # Arguments
/// * `segments_list` - List of segment dictionaries
/// * `min_chapter_duration` - Minimum duration for a chapter (default 60.0s)
/// * `silence_threshold` - Gap duration that indicates chapter break (default 3.0s)
///
/// # Returns
/// * List of chapter markers with timestamps
#[pyfunction]
#[pyo3(signature = (segments_list, min_chapter_duration=60.0, silence_threshold=3.0))]
fn detect_chapters(
    py: Python<'_>,
    segments_list: &Bound<'_, PyList>,
    min_chapter_duration: f64,
    silence_threshold: f64,
) -> PyResult<Py<PyList>> {
    if segments_list.is_empty() {
        return Ok(PyList::empty(py).into());
    }

    let result = PyList::empty(py);

    // First chapter always starts at the beginning
    let first_item = segments_list.get_item(0)?;
    let first_segment = first_item.downcast::<PyDict>()?;
    let first_start: f64 = first_segment
        .get_item("start")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
        .extract()?;

    let mut chapter_start = first_start;
    let mut last_end = first_start;

    let dict = PyDict::new(py);
    dict.set_item("chapter", 1)?;
    dict.set_item("start", chapter_start)?;
    dict.set_item("timestamp", format_timestamp_internal(chapter_start))?;
    result.append(dict)?;

    for i in 1..segments_list.len() {
        let seg_item = segments_list.get_item(i)?;
        let segment = seg_item.downcast::<PyDict>()?;

        let seg_start: f64 = segment
            .get_item("start")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;

        let seg_end: f64 = segment
            .get_item("end")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;

        let gap = seg_start - last_end;
        let chapter_duration = seg_start - chapter_start;

        // Check for chapter break
        if gap >= silence_threshold && chapter_duration >= min_chapter_duration {
            let dict = PyDict::new(py);
            dict.set_item("chapter", result.len() + 1)?;
            dict.set_item("start", seg_start)?;
            dict.set_item("timestamp", format_timestamp_internal(seg_start))?;
            result.append(dict)?;

            chapter_start = seg_start;
        }

        last_end = seg_end;
    }

    Ok(result.into())
}

/// Formats timestamps for display (helper function)
fn format_timestamp_internal(seconds: f64) -> String {
    let hours = (seconds / 3600.0).floor() as u32;
    let mins = ((seconds % 3600.0) / 60.0).floor() as u32;
    let secs = (seconds % 60.0).floor() as u32;

    if hours > 0 {
        format!("{:02}:{:02}:{:02}", hours, mins, secs)
    } else {
        format!("{:02}:{:02}", mins, secs)
    }
}

#[pymodule]
fn _lowlevel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Add custom exception types for better error handling in Python
    m.add("VttError", m.py().get_type::<VttError>())?;
    m.add(
        "VttValidationError",
        m.py().get_type::<VttValidationError>(),
    )?;
    m.add("VttTimestampError", m.py().get_type::<VttTimestampError>())?;
    m.add("VttHeaderError", m.py().get_type::<VttHeaderError>())?;
    m.add("VttCueError", m.py().get_type::<VttCueError>())?;
    m.add("VttEscapingError", m.py().get_type::<VttEscapingError>())?;
    m.add("VttSequenceError", m.py().get_type::<VttSequenceError>())?;

    // Add main builder functions
    m.add_function(wrap_pyfunction!(build_transcript_from_json_files, m)?)?;
    m.add_function(wrap_pyfunction!(build_vtt_from_json_files, m)?)?;
    m.add_function(wrap_pyfunction!(build_vtt_from_records, m)?)?;
    m.add_function(wrap_pyfunction!(build_vtt_string, m)?)?;

    // Add validation functions
    m.add_function(wrap_pyfunction!(validate_vtt_file, m)?)?;
    m.add_function(wrap_pyfunction!(validate_segments, m)?)?;
    m.add_function(wrap_pyfunction!(validate_cue_sequence, m)?)?;

    // Add parser functions
    m.add_function(wrap_pyfunction!(parse_vtt_file, m)?)?;
    m.add_function(wrap_pyfunction!(parse_vtt_string, m)?)?;

    // Add utility functions
    m.add_function(wrap_pyfunction!(escape_vtt_text_py, m)?)?;
    m.add_function(wrap_pyfunction!(unescape_vtt_text, m)?)?;

    // Add transformation functions
    m.add_function(wrap_pyfunction!(merge_segments, m)?)?;
    m.add_function(wrap_pyfunction!(clamp_to_duration, m)?)?;
    m.add_function(wrap_pyfunction!(split_long_segments, m)?)?;
    m.add_function(wrap_pyfunction!(shift_timestamps, m)?)?;
    m.add_function(wrap_pyfunction!(filter_segments_by_time, m)?)?;

    // Add timestamp conversion functions
    m.add_function(wrap_pyfunction!(seconds_to_timestamp, m)?)?;
    m.add_function(wrap_pyfunction!(timestamp_to_seconds, m)?)?;

    // Add statistics functions
    m.add_function(wrap_pyfunction!(get_segments_stats, m)?)?;

    // Add podcast processing functions
    m.add_function(wrap_pyfunction!(remove_filler_words, m)?)?;
    m.add_function(wrap_pyfunction!(group_by_speaker, m)?)?;
    m.add_function(wrap_pyfunction!(filter_by_confidence, m)?)?;
    m.add_function(wrap_pyfunction!(words_to_segments, m)?)?;
    m.add_function(wrap_pyfunction!(remove_repeated_phrases, m)?)?;
    m.add_function(wrap_pyfunction!(detect_chapters, m)?)?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_escape_vtt_text() {
        assert_eq!(escape_vtt_text("plain text"), "plain text");
        assert_eq!(escape_vtt_text("a & b"), "a &amp; b");
        assert_eq!(escape_vtt_text("<tag>"), "&lt;tag&gt;");
        assert_eq!(escape_vtt_text("a --> b"), "a --&gt; b");
        assert_eq!(escape_vtt_text("&<>"), "&amp;&lt;&gt;");
        assert_eq!(escape_vtt_text("Tom & Jerry <3"), "Tom &amp; Jerry &lt;3");
    }

    #[test]
    fn test_unescape_vtt_text() {
        assert_eq!(unescape_vtt_text("plain text"), "plain text");
        assert_eq!(unescape_vtt_text("a &amp; b"), "a & b");
        assert_eq!(unescape_vtt_text("&lt;tag&gt;"), "<tag>");
        assert_eq!(unescape_vtt_text("a --&gt; b"), "a --> b");
        assert_eq!(unescape_vtt_text("&nbsp;"), "\u{00A0}");
        assert_eq!(unescape_vtt_text("&lrm;"), "\u{200E}");
        assert_eq!(unescape_vtt_text("&rlm;"), "\u{200F}");
    }

    #[test]
    fn test_format_timestamp_flexible_long_format() {
        assert_eq!(format_timestamp_flexible(0.0, false), "00:00:00.000");
        assert_eq!(format_timestamp_flexible(1.0, false), "00:00:01.000");
        assert_eq!(format_timestamp_flexible(61.5, false), "00:01:01.500");
        assert_eq!(format_timestamp_flexible(3661.999, false), "01:01:01.999");
        assert_eq!(format_timestamp_flexible(3600.0, false), "01:00:00.000");
    }

    #[test]
    fn test_format_timestamp_flexible_short_format() {
        assert_eq!(format_timestamp_flexible(0.0, true), "00:00.000");
        assert_eq!(format_timestamp_flexible(1.0, true), "00:01.000");
        assert_eq!(format_timestamp_flexible(61.5, true), "01:01.500");
        assert_eq!(format_timestamp_flexible(599.999, true), "09:59.999");
        // When hours > 0, should use long format even with short=true
        assert_eq!(format_timestamp_flexible(3661.0, true), "01:01:01.000");
    }

    #[test]
    fn test_is_valid_timestamp() {
        // Valid long format
        assert!(is_valid_timestamp("00:00:00.000"));
        assert!(is_valid_timestamp("01:23:45.678"));
        assert!(is_valid_timestamp("99:59:59.999"));

        // Valid short format
        assert!(is_valid_timestamp("00:00.000"));
        assert!(is_valid_timestamp("01:30.500"));
        assert!(is_valid_timestamp("59:59.999"));

        // Invalid: missing milliseconds
        assert!(!is_valid_timestamp("00:00:00"));
        assert!(!is_valid_timestamp("00:00"));

        // Invalid: wrong millisecond length
        assert!(!is_valid_timestamp("00:00:00.0"));
        assert!(!is_valid_timestamp("00:00:00.00"));
        assert!(!is_valid_timestamp("00:00:00.0000"));

        // Invalid: seconds > 59
        assert!(!is_valid_timestamp("00:00:60.000"));
        assert!(!is_valid_timestamp("00:60.000"));

        // Invalid: minutes > 59 in long format
        assert!(!is_valid_timestamp("00:60:00.000"));

        // Invalid: wrong separator
        assert!(!is_valid_timestamp("00-00-00.000"));
    }

    #[test]
    fn test_validate_segment_success() {
        let segment = Segment {
            id: 1,
            start: 0.0,
            end: 2.5,
            text: "Valid text".to_string(),
        };
        assert!(validate_segment(&segment).is_ok());
    }

    #[test]
    fn test_validate_segment_negative_start() {
        let segment = Segment {
            id: 1,
            start: -1.0,
            end: 2.5,
            text: "Text".to_string(),
        };
        assert!(validate_segment(&segment).is_err());
    }

    #[test]
    fn test_validate_segment_negative_end() {
        let segment = Segment {
            id: 1,
            start: 0.0,
            end: -1.0,
            text: "Text".to_string(),
        };
        assert!(validate_segment(&segment).is_err());
    }

    #[test]
    fn test_validate_segment_end_before_start() {
        let segment = Segment {
            id: 1,
            start: 5.0,
            end: 2.5,
            text: "Text".to_string(),
        };
        assert!(validate_segment(&segment).is_err());
    }

    #[test]
    fn test_validate_segment_empty_text() {
        let segment = Segment {
            id: 1,
            start: 0.0,
            end: 2.5,
            text: "   ".to_string(),
        };
        assert!(validate_segment(&segment).is_err());
    }

    #[test]
    fn test_validate_segment_max_timestamp() {
        let segment = Segment {
            id: 1,
            start: 0.0,
            end: MAX_TIMESTAMP_SECONDS,
            text: "Text".to_string(),
        };
        assert!(validate_segment(&segment).is_ok());

        let segment_over = Segment {
            id: 1,
            start: 0.0,
            end: MAX_TIMESTAMP_SECONDS + 1.0,
            text: "Text".to_string(),
        };
        assert!(validate_segment(&segment_over).is_err());
    }

    #[test]
    fn test_validate_segment_arrow_in_text() {
        let segment = Segment {
            id: 1,
            start: 0.0,
            end: 2.5,
            text: "Text with --> arrow".to_string(),
        };
        assert!(validate_segment(&segment).is_err());
    }

    #[test]
    fn test_prepare_cue_text_flatten_newlines() {
        let config = VttConfig {
            escape_special_chars: false,
            flatten_newlines: true,
            ..Default::default()
        };
        assert_eq!(
            prepare_cue_text("Line 1\nLine 2\rLine 3\tLine 4", &config),
            "Line 1 Line 2 Line 3 Line 4"
        );
    }

    #[test]
    fn test_prepare_cue_text_preserve_newlines() {
        let config = VttConfig {
            escape_special_chars: false,
            flatten_newlines: false,
            ..Default::default()
        };
        let result = prepare_cue_text("Line 1\nLine 2", &config);
        assert!(result.contains("Line 1"));
        assert!(result.contains("Line 2"));
    }

    #[test]
    fn test_prepare_cue_text_escape() {
        let config = VttConfig {
            escape_special_chars: true,
            flatten_newlines: true,
            ..Default::default()
        };
        assert_eq!(prepare_cue_text("Tom & Jerry", &config), "Tom &amp; Jerry");
    }

    #[test]
    fn test_prepare_cue_text_no_escape() {
        let config = VttConfig {
            escape_special_chars: false,
            flatten_newlines: true,
            ..Default::default()
        };
        assert_eq!(prepare_cue_text("Tom & Jerry", &config), "Tom & Jerry");
    }

    #[test]
    fn test_format_timestamp_internal() {
        assert_eq!(format_timestamp_internal(0.0), "00:00");
        assert_eq!(format_timestamp_internal(90.0), "01:30");
        assert_eq!(format_timestamp_internal(3661.0), "01:01:01");
        assert_eq!(format_timestamp_internal(59.0), "00:59");
    }

    fn seg(id: u32, start: f64, end: f64) -> Segment {
        Segment {
            id,
            start,
            end,
            text: "text".to_string(),
        }
    }

    #[test]
    fn test_sequence_valid_ordered_list() {
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 3.0, 5.0), seg(3, 6.0, 8.0)];
        assert!(check_cue_sequence(&segments, None, None).is_ok());
    }

    #[test]
    fn test_sequence_rejects_overlap() {
        // Cue 2 starts before cue 1 ends: the silent-corruption case this
        // whole change exists to surface.
        let segments = vec![seg(1, 0.0, 5.0), seg(2, 3.0, 7.0)];
        assert!(check_cue_sequence(&segments, None, None).is_err());
    }

    #[test]
    fn test_sequence_rejects_out_of_order() {
        let segments = vec![seg(1, 10.0, 12.0), seg(2, 2.0, 4.0)];
        assert!(check_cue_sequence(&segments, None, None).is_err());
    }

    #[test]
    fn test_sequence_accepts_exact_abutment() {
        // Normal chunker output; must not be an error, or every well-formed
        // transcript would fail.
        let segments = vec![seg(1, 0.0, 2.5), seg(2, 2.5, 5.0)];
        assert!(check_cue_sequence(&segments, None, None).is_ok());
    }

    #[test]
    fn test_sequence_rejects_zero_length_cue() {
        let segments = vec![seg(1, 1.0, 1.0)];
        assert!(check_cue_sequence(&segments, None, None).is_err());
    }

    #[test]
    fn test_sequence_rejects_gap_below_minimum() {
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 2.05, 4.0)];
        assert!(check_cue_sequence(&segments, Some(0.1), None).is_err());
    }

    #[test]
    fn test_sequence_accepts_gap_meeting_minimum() {
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 2.2, 4.0)];
        assert!(check_cue_sequence(&segments, Some(0.1), None).is_ok());
    }

    #[test]
    fn test_sequence_rejects_duration_overrun() {
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 3.0, 12.0)];
        assert!(check_cue_sequence(&segments, None, Some(10.0)).is_err());
    }

    #[test]
    fn test_sequence_rejects_start_past_duration() {
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 11.0, 12.0)];
        assert!(check_cue_sequence(&segments, None, Some(10.0)).is_err());
    }

    #[test]
    fn test_sequence_accepts_cue_ending_exactly_at_duration() {
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 3.0, 10.0)];
        assert!(check_cue_sequence(&segments, None, Some(10.0)).is_ok());
    }

    #[test]
    fn test_sequence_empty_and_single_lists_are_valid() {
        assert!(check_cue_sequence(&[], None, None).is_ok());
        let single = vec![seg(1, 0.0, 2.0)];
        assert!(check_cue_sequence(&single, None, None).is_ok());
    }

    // Quantization behavior. These pin the decision to compare whole
    // milliseconds rather than raw f64: without them, a refactor back to f64
    // comparison would pass the suite while making exact abutment depend on
    // whichever arithmetic produced each timestamp.

    #[test]
    fn test_sequence_abutment_survives_floating_point_arithmetic() {
        // 0.1 * 3 is 0.30000000000000004, not 0.3. Quantized to milliseconds
        // both are 300, so this abuts exactly and must pass.
        let segments = vec![seg(1, 0.0, 0.1 + 0.1 + 0.1), seg(2, 0.3, 1.0)];
        assert!(check_cue_sequence(&segments, None, None).is_ok());
    }

    #[test]
    fn test_sequence_ignores_sub_millisecond_overlap() {
        // Overlap of 0.0001s cannot be represented in a WebVTT timestamp, so
        // it cannot affect a player and must not be reported.
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 1.9999, 4.0)];
        assert!(check_cue_sequence(&segments, None, None).is_ok());
    }

    #[test]
    fn test_sequence_rejects_cue_zero_length_only_after_quantization() {
        // Spans 0.0001s, which serializes to a zero-length cue.
        let segments = vec![seg(1, 1.0, 1.0001)];
        assert!(check_cue_sequence(&segments, None, None).is_err());
    }

    #[test]
    fn test_sequence_min_gap_zero_admits_abutting_cues() {
        // Gap comparison is strictly less-than, so an explicit 0.0 still
        // allows abutment.
        let segments = vec![seg(1, 0.0, 2.0), seg(2, 2.0, 4.0)];
        assert!(check_cue_sequence(&segments, Some(0.0), None).is_ok());
    }

    #[test]
    fn test_sequence_quantization_matches_written_timestamps() {
        // The validator must agree with the write path about what a time is.
        let boundary = 2.0004; // writes as 00:00:02.000
        assert_eq!(to_millis(boundary), 2000);
        assert_eq!(format_timestamp_flexible(boundary, false), "00:00:02.000");
        let segments = vec![seg(1, 0.0, 2.0), seg(2, boundary, 4.0)];
        assert!(check_cue_sequence(&segments, None, None).is_ok());
    }

    #[test]
    fn test_sequence_error_message_names_both_cues_and_times() {
        // A failure must be actionable from a log line alone, and must report
        // the caller's own unquantized values.
        let segments = vec![seg(7, 0.0, 5.0), seg(8, 3.0, 7.0)];
        let err = check_cue_sequence(&segments, None, None).unwrap_err();
        let msg = err.to_string();
        assert!(msg.contains('7'), "missing previous segment id: {}", msg);
        assert!(msg.contains('8'), "missing offending segment id: {}", msg);
        assert!(msg.contains('3'), "missing start time: {}", msg);
        assert!(msg.contains('5'), "missing previous end time: {}", msg);
    }
}
