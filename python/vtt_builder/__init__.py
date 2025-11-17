"""
VTT Builder - WebVTT file generation with spec compliance.

This module provides high-performance tools for creating and validating
WebVTT (Web Video Text Tracks) files from transcript data.
"""

from vtt_builder._lowlevel import (
    # Main builder functions
    build_transcript_from_json_files,
    build_vtt_from_json_files,
    build_vtt_from_records,
    # Validation functions
    validate_vtt_file,
    validate_segments,
    # Utility functions
    escape_vtt_text_py as escape_vtt_text,
    unescape_vtt_text,
    # Exception types
    VttError,
    VttValidationError,
    VttTimestampError,
    VttHeaderError,
    VttCueError,
    VttEscapingError,
)

__version__ = "0.3.0"

__all__ = [
    # Builder functions
    "build_vtt_from_records",
    "build_transcript_from_json_files",
    "build_vtt_from_json_files",
    # Validation
    "validate_vtt_file",
    "validate_segments",
    # Utilities
    "escape_vtt_text",
    "unescape_vtt_text",
    # Exceptions
    "VttError",
    "VttValidationError",
    "VttTimestampError",
    "VttHeaderError",
    "VttCueError",
    "VttEscapingError",
]
