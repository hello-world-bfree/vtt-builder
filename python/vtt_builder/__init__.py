"""
VTT Builder - WebVTT file generation with spec compliance.

This module provides high-performance tools for creating, validating,
and manipulating WebVTT (Web Video Text Tracks) files from transcript data.
"""

from vtt_builder._lowlevel import (
    VttCueError,
    # Exception types
    VttError,
    VttEscapingError,
    VttHeaderError,
    VttSequenceError,
    VttTimestampError,
    VttValidationError,
    # Main builder functions
    build_transcript_from_json_files,
    build_vtt_from_json_files,
    build_vtt_from_records,
    build_vtt_string,
    clamp_to_duration,
    detect_chapters,
    filter_by_confidence,
    filter_segments_by_time,
    # Statistics functions
    get_segments_stats,
    group_by_speaker,
    # Segment transformation functions
    merge_segments,
    # Parser functions
    parse_vtt_file,
    parse_vtt_string,
    # Podcast processing functions
    remove_filler_words,
    remove_repeated_phrases,
    # Timestamp conversion functions
    seconds_to_timestamp,
    shift_timestamps,
    split_long_segments,
    timestamp_to_seconds,
    unescape_vtt_text,
    validate_cue_sequence,
    validate_segments,
    # Validation functions
    validate_vtt_file,
    words_to_segments,
)
from vtt_builder._lowlevel import (
    # Escape/Unescape utilities
    escape_vtt_text_py as escape_vtt_text,
)

__version__ = "0.6.0"

__all__ = [
    # Parser functions
    "parse_vtt_file",
    "parse_vtt_string",
    # Builder functions
    "build_vtt_from_records",
    "build_transcript_from_json_files",
    "build_vtt_from_json_files",
    "build_vtt_string",
    # Validation
    "validate_vtt_file",
    "validate_segments",
    "validate_cue_sequence",
    # Escape/Unescape
    "escape_vtt_text",
    "unescape_vtt_text",
    # Transformations
    "merge_segments",
    "clamp_to_duration",
    "split_long_segments",
    "shift_timestamps",
    "filter_segments_by_time",
    # Timestamp conversions
    "seconds_to_timestamp",
    "timestamp_to_seconds",
    # Statistics
    "get_segments_stats",
    # Podcast processing
    "remove_filler_words",
    "group_by_speaker",
    "filter_by_confidence",
    "words_to_segments",
    "remove_repeated_phrases",
    "detect_chapters",
    # Exceptions
    "VttError",
    "VttValidationError",
    "VttTimestampError",
    "VttHeaderError",
    "VttCueError",
    "VttEscapingError",
    "VttSequenceError",
]
