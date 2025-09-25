use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde::Deserialize;
use std::fs::File;
use std::io::{BufRead, BufReader, Write};

#[derive(Deserialize, Debug)]
struct Segment {
    #[allow(dead_code)]
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

fn map_io_error(e: std::io::Error) -> PyErr {
    pyo3::exceptions::PyIOError::new_err(e.to_string())
}

fn validation_error(msg: &str) -> PyErr {
    pyo3::exceptions::PyValueError::new_err(msg.to_string())
}

/// Formats a timestamp in seconds to "HH:MM:SS.mmm" format.
fn format_timestamp(seconds: f64) -> String {
    let total_millis = (seconds * 1000.0).round() as u64;
    let hours = total_millis / 3_600_000;
    let minutes = (total_millis / 60_000) % 60;
    let secs = (total_millis / 1_000) % 60;
    let millis = total_millis % 1_000;
    format!("{:02}:{:02}:{:02}.{:03}", hours, minutes, secs, millis)
}

/// Writes segments to the VTT file, updating the index and offset.
fn write_segments_to_vtt<W: Write>(
    segments: &[Segment],
    offset: f64,
    starting_index: usize,
    output: &mut W,
) -> Result<(usize, f64), std::io::Error> {
    let mut index = starting_index;

    for segment in segments {
        let start_time = format_timestamp(segment.start + offset);
        let end_time = format_timestamp(segment.end + offset);
        let clean_text = segment
            .text
            .replace("\n", " ")
            .replace('\r', " ")
            .replace('\t', " ")
            .split_whitespace()
            .collect::<Vec<&str>>()
            .join(" ");
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
#[pyfunction]
fn build_vtt_from_json_files(file_paths: Vec<String>, output_file: &str) -> PyResult<()> {
    let mut output = File::create(output_file).map_err(map_io_error)?;
    writeln!(output, "WEBVTT\n").map_err(map_io_error)?;

    let mut total_offset = 0.0;
    let mut current_index = 1;

    for file_path in file_paths {
        let file = File::open(&file_path).map_err(map_io_error)?;
        let reader = BufReader::new(file);
        let transcript: Transcript = serde_json::from_reader(reader)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        let (new_index, new_offset) = write_segments_to_vtt(
            &transcript.segments,
            total_offset,
            current_index,
            &mut output,
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

/// Builds a VTT file from a list of Python dictionaries representing segments.
#[pyfunction]
fn build_vtt_from_records(segments_list: &Bound<'_, PyList>, output_file: &str) -> PyResult<()> {
    let mut output = File::create(output_file).map_err(map_io_error)?;
    writeln!(output, "WEBVTT\n").map_err(map_io_error)?;

    let mut segments = Vec::new();

    for segment in segments_list.iter() {
        let segment_dict = segment.downcast::<PyDict>()?;

        let id: u32 = segment_dict
            .get_item("id")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'id' field"))?
            .extract()?;
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

        segments.push(Segment {
            id,
            start,
            end,
            text: text.trim().to_string(),
        });
    }

    write_segments_to_vtt(&segments, 0.0, 1, &mut output).map_err(map_io_error)?;

    Ok(())
}

#[pyfunction]
fn validate_vtt_file(vtt_file: &str) -> PyResult<bool> {
    let file = File::open(vtt_file).map_err(map_io_error)?;
    let reader = BufReader::new(file);

    let mut lines = reader.lines();

    // Check for the "WEBVTT" header
    if let Some(line_result) = lines.next() {
        let header = line_result.map_err(map_io_error)?;
        if header.trim() != "WEBVTT" {
            return Err(validation_error("Missing or incorrect WEBVTT header"));
        }
    } else {
        return Err(validation_error("Empty file"));
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

        // Check if this is a NOTE or STYLE block (should be skipped)
        if line_trimmed.starts_with("NOTE") || line_trimmed.starts_with("STYLE") {
            // Skip all lines until we find an empty line or EOF
            for note_line_result in &mut lines {
                let note_content = note_line_result.map_err(map_io_error)?;
                println!("Skipping line below NOTE/STYLE block: {}", note_content);
                if note_content.trim().is_empty() {
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
                        "Invalid timing line after cue identifier: '{}'",
                        next_line_trimmed
                    );
                    return Err(validation_error(&msg));
                }
            } else {
                return Err(validation_error(
                    "Expected timing line after cue identifier",
                ));
            }
        } else {
            if !is_valid_timing(line_trimmed) {
                let msg = format!("Invalid timing line: '{}'", line_trimmed);
                return Err(validation_error(&msg));
            }
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
            return Err(validation_error("Cue missing text"));
        }
    }

    Ok(true)
}

fn is_valid_timing(line: &str) -> bool {
    // The timing line should have the format "start_time --> end_time"
    let parts: Vec<&str> = line.split("-->").collect();
    if parts.len() != 2 {
        return false;
    }

    let start_time = parts[0].trim();
    let end_time = parts[1].trim();

    is_valid_timestamp(start_time) && is_valid_timestamp(end_time)
}

fn is_valid_timestamp(timestamp: &str) -> bool {
    // Timestamp format: "HH:MM:SS.mmm" or "H:MM:SS.mmm"
    let parts: Vec<&str> = timestamp.split('.').collect();
    if parts.len() != 2 {
        return false;
    }

    let time_part = parts[0];
    let millis_part = parts[1];

    if millis_part.len() != 3 || !millis_part.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }

    let time_parts: Vec<&str> = time_part.split(':').collect();
    if time_parts.len() != 3 {
        return false;
    }

    for part in time_parts {
        if !part.chars().all(|c| c.is_ascii_digit()) {
            return false;
        }
    }

    true
}

#[pymodule]
fn _lowlevel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_transcript_from_json_files, m)?)?;
    m.add_function(wrap_pyfunction!(build_vtt_from_json_files, m)?)?;
    m.add_function(wrap_pyfunction!(build_vtt_from_records, m)?)?;
    m.add_function(wrap_pyfunction!(validate_vtt_file, m)?)?;
    Ok(())
}
