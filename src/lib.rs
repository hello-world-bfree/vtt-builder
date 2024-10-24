use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde::Deserialize;
use std::fs::File;
use std::io::{BufReader, Write, BufRead};

#[derive(Deserialize, Debug)]
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
        writeln!(
            output,
            "{}\n{} --> {}\n{}\n",
            index,
            start_time,
            end_time,
            segment.text.trim().to_string()
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
fn build_vtt_from_json_files(file_paths: Vec<&str>, output_file: &str) -> PyResult<()> {
    let mut output = File::create(output_file)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
    writeln!(output, "WEBVTT\n")
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

    let mut total_offset = 0.0;
    let mut current_index = 1;

    for file_path in file_paths {
        let file = File::open(file_path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        let reader = BufReader::new(file);
        let transcript: Transcript = serde_json::from_reader(reader)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        let (new_index, new_offset) = write_segments_to_vtt(
            &transcript.segments,
            total_offset,
            current_index,
            &mut output,
        )
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

        current_index = new_index;
        total_offset = new_offset;
    }

    Ok(())
}

#[pyfunction]
fn build_transcript_from_json_files(file_paths: Vec<&str>, output_file: &str) -> PyResult<()> {
    let mut output = File::create(output_file)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

    for (index, file_path) in file_paths.iter().enumerate() {
        let file = File::open(file_path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        let reader = BufReader::new(file);
        let transcript: Transcript = serde_json::from_reader(reader)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        writeln!(output, "{}", transcript.transcript.trim().to_string())
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

        if index < file_paths.len() - 1 {
            writeln!(output).map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        }
    }

    Ok(())
}

/// Builds a VTT file from a list of Python dictionaries representing segments.
#[pyfunction]
fn build_vtt_from_records(_py: Python, segments_list: &PyList, output_file: &str) -> PyResult<()> {
    let mut output = File::create(output_file)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
    writeln!(output, "WEBVTT\n")
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

    let mut segments = Vec::new();

    for segment in segments_list.iter() {
        let segment_dict = segment.downcast::<PyDict>()?;

        let id: u32 = segment_dict
            .get_item("id")
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'id' field"))?
            .extract()?;
        let start: f64 = segment_dict
            .get_item("start")
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'start' field"))?
            .extract()?;
        let end: f64 = segment_dict
            .get_item("end")
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'end' field"))?
            .extract()?;
        let text: String = segment_dict
            .get_item("text")
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'text' field"))?
            .extract()?;
        let text = text.trim().to_string();

        segments.push(Segment { id, start, end, text });
    }

    write_segments_to_vtt(&segments, 0.0, 1, &mut output)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;

    Ok(())
}

#[pyfunction]
fn validate_vtt_file(vtt_file: &str) -> PyResult<bool> {
    let file = File::open(vtt_file)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
    let reader = BufReader::new(file);

    let mut lines = reader.lines();

    // Check for the "WEBVTT" header
    if let Some(Ok(header)) = lines.next() {
        if header.trim() != "WEBVTT" {
            return Ok(false);
        }
    } else {
        return Ok(false);
    }

    // Skip optional metadata headers until an empty line
    for line in &mut lines {
        match line {
            Ok(ref content) if content.trim().is_empty() => break,
            Ok(_) => continue,
            Err(_) => return Ok(false),
        }
    }

    // Validate the cues
    while let Some(Ok(line)) = lines.next() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        // Optional cue identifier
        let mut timing_line = line.to_string();

        if !line.contains("-->") {
            if let Some(Ok(next_line)) = lines.next() {
                let next_line_trimmed = next_line.trim();
                if !is_valid_timing(next_line_trimmed) {
                    return Ok(false);
                }
                timing_line = next_line_trimmed.to_string();
            } else {
                return Ok(false);
            }
        } else {
            if !is_valid_timing(line) {
                return Ok(false);
            }
        }

        let mut has_text = false;
        for cue_line in &mut lines {
            match cue_line {
                Ok(ref content) if content.trim().is_empty() => break,
                Ok(_) => {
                    has_text = true;
                    continue;
                }
                Err(_) => return Ok(false),
            }
        }

        if !has_text {
            return Ok(false);
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

    if millis_part.len() != 3 || !millis_part.chars().all(|c| c.is_digit(10)) {
        return false;
    }

    let time_parts: Vec<&str> = time_part.split(':').collect();
    if time_parts.len() != 3 {
        return false;
    }

    for part in time_parts {
        if !part.chars().all(|c| c.is_digit(10)) {
            return false;
        }
    }

    true
}

#[pymodule]
fn _lowlevel(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_transcript_from_json_files, m)?)?;
    m.add_function(wrap_pyfunction!(build_vtt_from_json_files, m)?)?;
    m.add_function(wrap_pyfunction!(build_vtt_from_records, m)?)?;
    m.add_function(wrap_pyfunction!(validate_vtt_file, m)?)?;
    Ok(())
}
