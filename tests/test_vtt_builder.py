import json
import os
import tempfile

import pytest
from vtt_builder import (
    VttCueError,
    VttError,
    VttHeaderError,
    VttSequenceError,
    VttTimestampError,
    VttValidationError,
    build_transcript_from_json_files,
    build_vtt_from_json_files,
    build_vtt_from_records,
    build_vtt_string,
    clamp_to_duration,
    detect_chapters,
    escape_vtt_text,
    filter_by_confidence,
    filter_segments_by_time,
    get_segments_stats,
    group_by_speaker,
    merge_segments,
    parse_vtt_file,
    parse_vtt_string,
    remove_filler_words,
    remove_repeated_phrases,
    seconds_to_timestamp,
    shift_timestamps,
    split_long_segments,
    timestamp_to_seconds,
    unescape_vtt_text,
    validate_cue_sequence,
    validate_segments,
    validate_vtt_file,
    words_to_segments,
)


@pytest.fixture
def sample_transcript_data():
    """Sample transcript data for testing."""
    return {
        "transcript": "Hello world. This is a test.",
        "segments": [
            {"id": 1, "start": 0.0, "end": 2.5, "text": "Hello world"},
            {"id": 2, "start": 2.5, "end": 5.0, "text": "This is a test"},
        ],
    }


@pytest.fixture
def sample_transcript_data_2():
    """Second sample for multi-file tests."""
    return {
        "transcript": "Second transcript file.",
        "segments": [
            {"id": 3, "start": 0.0, "end": 1.5, "text": "Second transcript"},
            {"id": 4, "start": 1.5, "end": 3.0, "text": "file"},
        ],
    }


@pytest.fixture
def sample_transcript_data_3():
    """Second sample for multi-file tests."""
    return {
        "transcript": "Third transcript file.",
        "segments": [
            {"id": 3, "start": 0.0, "end": 1.5, "text": "Third\n\n\n transcript"},
            {"id": 4, "start": 1.5, "end": 3.0, "text": "file"},
        ],
    }


@pytest.fixture
def temp_json_file(sample_transcript_data):
    """Create a temporary JSON file with sample data."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample_transcript_data, f)
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def temp_output_file():
    """Create a temporary output file path."""
    with tempfile.NamedTemporaryFile(suffix=".vtt", delete=False) as f:
        temp_path = f.name
    os.unlink(temp_path)  # Delete immediately, we just need the path
    yield temp_path
    # Cleanup after test
    if os.path.exists(temp_path):
        os.unlink(temp_path)


class TestVTTBuilder:
    """Test suite for VTT builder functions."""

    def test_build_vtt_from_json_files_single_file(self, temp_json_file, temp_output_file):
        """Test building VTT from a single JSON file."""
        build_vtt_from_json_files([temp_json_file], temp_output_file)

        # Verify output file exists
        assert os.path.exists(temp_output_file)

        # Read and verify content
        with open(temp_output_file) as f:
            content = f.read()

        assert content.startswith("WEBVTT\n")
        assert "1\n00:00:00.000 --> 00:00:02.500\nHello world" in content
        assert "2\n00:00:02.500 --> 00:00:05.000\nThis is a test" in content

    def test_build_vtt_from_json_files_multiple_files(
        self, sample_transcript_data, sample_transcript_data_2, temp_output_file
    ):
        """Test building VTT from multiple JSON files."""
        # Create two temp files
        temp_files = []
        for data in [sample_transcript_data, sample_transcript_data_2]:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(data, f)
                temp_files.append(f.name)

        try:
            build_vtt_from_json_files(temp_files, temp_output_file)

            with open(temp_output_file) as f:
                content = f.read()

            assert content.startswith("WEBVTT\n")
            # Check that segments are properly offset
            assert "1\n00:00:00.000 --> 00:00:02.500\nHello world" in content
            assert "2\n00:00:02.500 --> 00:00:05.000\nThis is a test" in content
            # Second file segments should be offset by 5.0 seconds
            assert "3\n00:00:05.000 --> 00:00:06.500\nSecond transcript" in content
            assert "4\n00:00:06.500 --> 00:00:08.000\nfile" in content

        finally:
            # Cleanup temp files
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)

    def test_build_vtt_from_json_files_nonexistent_file(self, temp_output_file):
        """Test error handling for nonexistent input file."""
        with pytest.raises(IOError):
            build_vtt_from_json_files(["/nonexistent/file.json"], temp_output_file)

    def test_build_vtt_from_json_files_invalid_json(self, temp_output_file):
        """Test error handling for invalid JSON."""
        # Create temp file with invalid JSON
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            temp_invalid = f.name

        try:
            with pytest.raises(ValueError):
                build_vtt_from_json_files([temp_invalid], temp_output_file)
        finally:
            os.unlink(temp_invalid)

    def test_build_transcript_from_json_files_single_file(self, temp_json_file, temp_output_file):
        """Test building transcript from a single JSON file."""
        build_transcript_from_json_files([temp_json_file], temp_output_file)

        assert os.path.exists(temp_output_file)

        with open(temp_output_file) as f:
            content = f.read().strip()

        assert content == "Hello world. This is a test."

    def test_build_transcript_from_json_files_multiple_files(
        self, sample_transcript_data, sample_transcript_data_2, temp_output_file
    ):
        """Test building transcript from multiple JSON files."""
        temp_files = []
        for data in [sample_transcript_data, sample_transcript_data_2]:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(data, f)
                temp_files.append(f.name)

        try:
            build_transcript_from_json_files(temp_files, temp_output_file)

            with open(temp_output_file) as f:
                content = f.read()

            expected = "Hello world. This is a test.\n\nSecond transcript file.\n"
            assert content == expected

        finally:
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)

    def test_build_vtt_from_records(self, temp_output_file):
        """Test building VTT from Python dictionary records."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "First segment"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Second segment"},
            {"id": 3, "start": 4.0, "end": 6.0, "text": "Third segment"},
        ]

        build_vtt_from_records(segments, temp_output_file)

        assert os.path.exists(temp_output_file)

        with open(temp_output_file) as f:
            content = f.read()

        assert content.startswith("WEBVTT\n")
        assert "1\n00:00:00.000 --> 00:00:02.000\nFirst segment" in content
        assert "2\n00:00:02.000 --> 00:00:04.000\nSecond segment" in content
        assert "3\n00:00:04.000 --> 00:00:06.000\nThird segment" in content

    def test_build_vtt_from_records_missing_fields(self, temp_output_file):
        """Test error handling for missing required fields."""
        incomplete_segments = [
            {"id": 1, "start": 0.0},  # Missing 'end' and 'text'
        ]

        with pytest.raises(KeyError):
            build_vtt_from_records(incomplete_segments, temp_output_file)

    def test_build_vtt_from_records_text_cleaning(self, temp_output_file):
        """Test that newlines in text are properly handled."""
        segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "Text with\n\n\nnewlines\nhere",
            },
            {"id": 2, "start": 2.0, "end": 4.0, "text": "  Whitespace text  "},
        ]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file) as f:
            content = f.read()

        # Newlines should be replaced with spaces, text should be trimmed
        assert "Text with newlines here" in content
        assert "Whitespace text" in content

    def test_validate_vtt_file_valid(self, temp_output_file):
        """Test validation of a valid VTT file."""
        valid_vtt = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
Hello world

2
00:00:02.500 --> 00:00:05.000
This is a test
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_valid_with_cue_identifiers(self, temp_output_file):
        """Test validation of VTT with cue identifiers."""
        valid_vtt = """WEBVTT

cue1
00:00:00.000 --> 00:00:02.500
Hello world

cue2
00:00:02.500 --> 00:00:05.000
This is a test
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_valid_with_metadata(self, temp_output_file):
        """Test validation of VTT with metadata headers."""
        valid_vtt = """WEBVTT
Kind: captions
Language: en

1
00:00:00.000 --> 00:00:02.500
Hello world

NOTE
This is a comment

2
00:00:02.500 --> 00:00:05.000
This is a test
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_missing_header(self, temp_output_file):
        """Test validation fails for missing WEBVTT header."""
        invalid_vtt = """1
00:00:00.000 --> 00:00:02.500
Hello world
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(VttHeaderError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_wrong_header(self, temp_output_file):
        """Test validation fails for incorrect header."""
        invalid_vtt = """WEBVTT-WRONG

1
00:00:00.000 --> 00:00:02.500
Hello world
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(VttHeaderError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_split_cue(self, temp_output_file):
        """Test validation fails for incorrect header."""
        invalid_vtt = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
Hello

world

2
00:00:03.000 --> 00:00:04.500
Hello world
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(VttTimestampError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_mixed_cue_ids(self, temp_output_file):
        """Test validation of a valid VTT file."""
        valid_vtt = """WEBVTT

00:00:00.000 --> 00:00:02.500
Hello world

2
00:00:02.500 --> 00:00:05.000
This is a test
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_empty(self, temp_output_file):
        """Test validation fails for empty file."""
        with open(temp_output_file, "w") as f:
            f.write("")

        with pytest.raises(VttHeaderError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_invalid_timing_format(self, temp_output_file):
        """Test validation fails for invalid timing format."""
        invalid_vtt = """WEBVTT

1
00:00:00 --> 00:00:02.500
Hello world
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(VttTimestampError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_invalid_timing_arrow(self, temp_output_file):
        """Test validation fails for invalid timing arrow."""
        invalid_vtt = """WEBVTT

1
00:00:00.000 -> 00:00:02.500
Hello world
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(VttTimestampError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_missing_cue_text(self, temp_output_file):
        """Test validation fails for cues without text."""
        invalid_vtt = """WEBVTT

1
00:00:00.000 --> 00:00:02.500

2
00:00:02.500 --> 00:00:05.000
This has text
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(VttCueError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_missing_timing_after_identifier(self, temp_output_file):
        """Test validation fails when cue identifier is not followed by timing."""
        invalid_vtt = """WEBVTT

cue1
Hello world without timing
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(VttTimestampError):
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_nonexistent(self):
        """Test validation fails for nonexistent file."""
        with pytest.raises(IOError):
            validate_vtt_file("/nonexistent/file.vtt")

    def test_validate_vtt_file_short_timestamps(self, temp_output_file):
        """Test validation accepts short timestamp format (MM:SS.mmm)."""
        valid_vtt = """WEBVTT

00:05.000 --> 00:10.000
Short format timestamps

01:30.500 --> 02:00.000
Another cue
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_with_bom(self, temp_output_file):
        """Test validation handles UTF-8 BOM correctly."""
        # Write file with BOM
        with open(temp_output_file, "wb") as f:
            f.write(b"\xef\xbb\xbfWEBVTT\n\n00:00:00.000 --> 00:00:05.000\nText\n")

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_with_header_text(self, temp_output_file):
        """Test validation accepts header with description text."""
        valid_vtt = """WEBVTT - My Video Captions

00:00:00.000 --> 00:00:05.000
Cue text
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_with_cue_settings(self, temp_output_file):
        """Test validation accepts cue settings after timestamp."""
        valid_vtt = """WEBVTT

00:00:00.000 --> 00:00:05.000 position:50% align:center
Centered text

00:00:05.000 --> 00:00:10.000 vertical:rl line:0
Vertical text
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True

    def test_validate_vtt_file_with_region_block(self, temp_output_file):
        """Test validation skips REGION blocks correctly."""
        valid_vtt = """WEBVTT

REGION
id:region1
width:50%
lines:3

00:00:00.000 --> 00:00:05.000
Cue text
"""
        with open(temp_output_file, "w") as f:
            f.write(valid_vtt)

        result = validate_vtt_file(temp_output_file)
        assert result is True


class TestCharacterEscaping:
    """Test character escaping functionality."""

    def test_escape_ampersand(self):
        """Test ampersand is escaped."""
        result = escape_vtt_text("Tom & Jerry")
        assert result == "Tom &amp; Jerry"

    def test_escape_less_than(self):
        """Test less-than is escaped."""
        result = escape_vtt_text("1 < 2")
        assert result == "1 &lt; 2"

    def test_escape_greater_than(self):
        """Test greater-than is escaped."""
        result = escape_vtt_text("2 > 1")
        assert result == "2 &gt; 1"

    def test_escape_all_characters(self):
        """Test all special characters are escaped."""
        result = escape_vtt_text("HTML <div> & <span> tags")
        assert result == "HTML &lt;div&gt; &amp; &lt;span&gt; tags"

    def test_escape_arrow_sequence(self):
        """Test --> substring is escaped."""
        result = escape_vtt_text("Tom --> Jerry")
        assert result == "Tom --&gt; Jerry"
        assert "-->" not in result

    def test_unescape_ampersand(self):
        """Test ampersand is unescaped."""
        result = unescape_vtt_text("Tom &amp; Jerry")
        assert result == "Tom & Jerry"

    def test_unescape_less_than(self):
        """Test less-than is unescaped."""
        result = unescape_vtt_text("1 &lt; 2")
        assert result == "1 < 2"

    def test_unescape_greater_than(self):
        """Test greater-than is unescaped."""
        result = unescape_vtt_text("2 &gt; 1")
        assert result == "2 > 1"

    def test_unescape_nbsp(self):
        """Test non-breaking space is unescaped."""
        result = unescape_vtt_text("Hello&nbsp;World")
        assert result == "Hello\u00a0World"

    def test_unescape_directional_marks(self):
        """Test directional marks are unescaped."""
        result = unescape_vtt_text("&lrm;Text&rlm;")
        assert result == "\u200eText\u200f"

    def test_escape_unescape_roundtrip(self):
        """Test escaping and unescaping returns original text."""
        original = "Tom & Jerry say 1 < 2 > 0"
        escaped = escape_vtt_text(original)
        unescaped = unescape_vtt_text(escaped)
        assert unescaped == original

    def test_build_vtt_escapes_special_chars(self, temp_output_file):
        """Test that building VTT automatically escapes special characters."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Tom & Jerry"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Use <html> tags"},
        ]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file) as f:
            content = f.read()

        assert "Tom &amp; Jerry" in content
        assert "Use &lt;html&gt; tags" in content

    def test_build_vtt_can_disable_escaping(self, temp_output_file):
        """Test that escaping can be disabled."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Tom & Jerry"},
        ]

        build_vtt_from_records(segments, temp_output_file, escape_text=False)

        with open(temp_output_file) as f:
            content = f.read()

        # Should NOT be escaped
        assert "Tom & Jerry" in content
        assert "&amp;" not in content


class TestSegmentValidation:
    """Test segment validation functionality."""

    def test_validate_segments_valid(self):
        """Test validation of valid segments."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Valid"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Also valid"},
        ]
        result = validate_segments(segments)
        assert result is True

    def test_validate_segments_negative_start(self):
        """Test validation fails for negative start time."""
        segments = [
            {"id": 1, "start": -1.0, "end": 2.0, "text": "Invalid"},
        ]
        with pytest.raises(VttTimestampError):
            validate_segments(segments)

    def test_validate_segments_negative_end(self):
        """Test validation fails for negative end time."""
        segments = [
            {"id": 1, "start": 0.0, "end": -1.0, "text": "Invalid"},
        ]
        with pytest.raises(VttTimestampError):
            validate_segments(segments)

    def test_validate_segments_end_before_start(self):
        """Test validation fails when end is before start."""
        segments = [
            {"id": 1, "start": 5.0, "end": 2.0, "text": "Invalid"},
        ]
        with pytest.raises(VttTimestampError):
            validate_segments(segments)

    def test_validate_segments_empty_text(self):
        """Test validation fails for empty text."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "   "},  # Only whitespace
        ]
        with pytest.raises(VttCueError):
            validate_segments(segments)

    def test_validate_segments_arrow_in_text(self):
        """Test validation fails for --> substring in text."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Arrow --> here"},
        ]
        with pytest.raises(VttCueError):
            validate_segments(segments)

    def test_validate_segments_timestamp_overflow(self):
        """Test validation fails for extremely large timestamps."""
        segments = [
            {
                "id": 1,
                "start": 400000.0,  # > 99:59:59.999
                "end": 400001.0,
                "text": "Too large",
            },
        ]
        with pytest.raises(VttTimestampError):
            validate_segments(segments)

    def test_build_vtt_validates_by_default(self, temp_output_file):
        """Test that building VTT validates segments by default."""
        invalid_segments = [
            {"id": 1, "start": 5.0, "end": 2.0, "text": "End before start"},
        ]
        with pytest.raises(VttTimestampError):
            build_vtt_from_records(invalid_segments, temp_output_file)

    def test_build_vtt_can_skip_validation(self, temp_output_file):
        """Test that validation can be disabled."""
        invalid_segments = [
            {
                "id": 1,
                "start": 5.0,
                "end": 2.0,
                "text": "End before start",
            },  # Invalid but won't be checked
        ]
        # Should not raise when validation is disabled
        build_vtt_from_records(invalid_segments, temp_output_file, validate_segments=False)
        assert os.path.exists(temp_output_file)

    def test_validate_segments_optional_id(self):
        """Test that segment ID is optional."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "No ID field"},
        ]
        result = validate_segments(segments)
        assert result is True


class TestMultilingualSupport:
    """Test support for multiple languages."""

    def test_spanish_characters(self, temp_output_file):
        """Test Spanish characters are preserved."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "El niño comió"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "¿Cómo estás? ¡Hola!"},
        ]
        build_vtt_from_records(segments, temp_output_file)
        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()
        assert "El niño comió" in content
        assert "¿Cómo estás? ¡Hola!" in content

    def test_portuguese_characters(self, temp_output_file):
        """Test Portuguese characters are preserved."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Ação e emoção"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "São Paulo é lindo"},
        ]
        build_vtt_from_records(segments, temp_output_file)
        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()
        assert "Ação e emoção" in content
        assert "São Paulo é lindo" in content

    def test_french_characters(self, temp_output_file):
        """Test French characters are preserved."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Café et crème brûlée"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Ça va très bien, merci"},
        ]
        build_vtt_from_records(segments, temp_output_file)
        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()
        assert "Café et crème brûlée" in content
        assert "Ça va très bien, merci" in content

    def test_german_characters(self, temp_output_file):
        """Test German characters are preserved."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Größe und Übung"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Schöne Grüße aus München"},
        ]
        build_vtt_from_records(segments, temp_output_file)
        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()
        assert "Größe und Übung" in content
        assert "Schöne Grüße aus München" in content

    def test_italian_characters(self, temp_output_file):
        """Test Italian characters are preserved."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Città e università"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "È più grande"},
        ]
        build_vtt_from_records(segments, temp_output_file)
        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()
        assert "Città e università" in content
        assert "È più grande" in content

    def test_polish_characters(self, temp_output_file):
        """Test Polish characters are preserved."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Łódź i Kraków"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Żółć i gęś"},
        ]
        build_vtt_from_records(segments, temp_output_file)
        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()
        assert "Łódź i Kraków" in content
        assert "Żółć i gęś" in content

    def test_mixed_language_with_special_chars(self, temp_output_file):
        """Test mixed languages with special characters that need escaping."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Español: niño & niña"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "Français: café < thé"},
            {"id": 3, "start": 4.0, "end": 6.0, "text": "Deutsch: größer > kleiner"},
        ]
        build_vtt_from_records(segments, temp_output_file)
        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()
        # Check escaping works with special characters
        assert "Español: niño &amp; niña" in content
        assert "Français: café &lt; thé" in content
        assert "Deutsch: größer &gt; kleiner" in content


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_segments_list(self, temp_output_file):
        """Test building VTT with empty segments list."""
        build_vtt_from_records([], temp_output_file)

        with open(temp_output_file) as f:
            content = f.read()

        # Should still have WEBVTT header
        assert content.strip() == "WEBVTT"

    def test_single_segment(self, temp_output_file):
        """Test building VTT with a single segment."""
        segments = [{"id": 1, "start": 0.0, "end": 2.0, "text": "Only segment"}]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file) as f:
            content = f.read()

        assert "WEBVTT" in content
        assert "1\n00:00:00.000 --> 00:00:02.000\nOnly segment" in content

    def test_zero_duration_segment_rejected(self, temp_output_file):
        """A zero-duration cue is rejected because it is never displayed.

        Changed in 0.6.0: this input previously produced a file containing a
        cue that no player would ever show. Sequence validation now rejects it,
        so the malformed output is surfaced as an error instead of written.
        """
        segments = [{"id": 1, "start": 1.0, "end": 1.0, "text": "Zero duration"}]

        with pytest.raises(VttSequenceError):
            build_vtt_from_records(segments, temp_output_file)

    def test_zero_duration_segment_written_when_validation_disabled(self, temp_output_file):
        """The opt-out preserves the pre-0.6.0 behavior exactly."""
        segments = [{"id": 1, "start": 1.0, "end": 1.0, "text": "Zero duration"}]

        build_vtt_from_records(segments, temp_output_file, validate_segments=False)

        with open(temp_output_file) as f:
            content = f.read()

        assert "1\n00:00:01.000 --> 00:00:01.000\nZero duration" in content

    def test_large_timestamps(self, temp_output_file):
        """Test with large timestamp values."""
        segments = [{"id": 1, "start": 3661.5, "end": 3665.0, "text": "Large timestamp"}]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file) as f:
            content = f.read()

        # Should format as 01:01:01.500 --> 01:01:05.000
        assert "01:01:01.500 --> 01:01:05.000" in content

    def test_special_characters_in_text(self, temp_output_file):
        """Test segments with special characters."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Text with émojis 🎉 and ñ"},
            {
                "id": 2,
                "start": 2.0,
                "end": 4.0,
                "text": "Quotes \"here\" and 'apostrophes'",
            },
        ]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file, encoding="utf-8") as f:
            content = f.read()

        assert "Text with émojis 🎉 and ñ" in content
        assert "Quotes \"here\" and 'apostrophes'" in content

    def test_exception_hierarchy(self):
        """Test that custom exceptions inherit correctly."""
        # All VTT exceptions should be subclasses of VttError
        assert issubclass(VttValidationError, VttError)
        assert issubclass(VttTimestampError, VttValidationError)
        assert issubclass(VttHeaderError, VttValidationError)
        assert issubclass(VttCueError, VttValidationError)

        # VttError itself should be a ValueError
        assert issubclass(VttError, ValueError)


class TestBuildVTTString:
    """Test in-memory VTT string building."""

    def test_build_vtt_string_basic(self):
        """Test basic in-memory VTT string generation."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.5, "text": "Hello world"},
            {"id": 2, "start": 2.5, "end": 5.0, "text": "This is a test"},
        ]
        result = build_vtt_string(segments)

        assert result.startswith("WEBVTT\n")
        assert "1\n00:00:00.000 --> 00:00:02.500\nHello world" in result
        assert "2\n00:00:02.500 --> 00:00:05.000\nThis is a test" in result

    def test_build_vtt_string_with_escaping(self):
        """Test that special characters are escaped."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Tom & Jerry"},
        ]
        result = build_vtt_string(segments)
        assert "Tom &amp; Jerry" in result

    def test_build_vtt_string_without_escaping(self):
        """Test disabling character escaping."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Tom & Jerry"},
        ]
        result = build_vtt_string(segments, escape_text=False)
        assert "Tom & Jerry" in result
        assert "&amp;" not in result

    def test_build_vtt_string_empty_segments(self):
        """Test with empty segments list."""
        result = build_vtt_string([])
        assert result.strip() == "WEBVTT"

    def test_build_vtt_string_with_validation(self):
        """Test that validation catches errors."""
        segments = [
            {"start": 5.0, "end": 2.0, "text": "Invalid"},
        ]
        with pytest.raises(VttTimestampError):
            build_vtt_string(segments, validate=True)

    def test_build_vtt_string_skip_validation(self):
        """Test skipping validation."""
        segments = [
            {"start": 5.0, "end": 2.0, "text": "Invalid but allowed"},
        ]
        # Should not raise when validation is disabled
        result = build_vtt_string(segments, validate=False)
        assert "Invalid but allowed" in result


class TestTimestampConversion:
    """Test timestamp conversion utilities."""

    def test_seconds_to_timestamp_zero(self):
        """Test converting zero seconds."""
        result = seconds_to_timestamp(0.0)
        assert result == "00:00:00.000"

    def test_seconds_to_timestamp_minutes(self):
        """Test converting minutes."""
        result = seconds_to_timestamp(125.5)
        assert result == "00:02:05.500"

    def test_seconds_to_timestamp_hours(self):
        """Test converting hours."""
        result = seconds_to_timestamp(3661.123)
        assert result == "01:01:01.123"

    def test_seconds_to_timestamp_large_value(self):
        """Test large timestamp value."""
        result = seconds_to_timestamp(86400.0)  # 24 hours
        assert result == "24:00:00.000"

    def test_seconds_to_timestamp_precision(self):
        """Test millisecond precision."""
        result = seconds_to_timestamp(1.001)
        assert result == "00:00:01.001"

    def test_timestamp_to_seconds_zero(self):
        """Test parsing zero timestamp."""
        result = timestamp_to_seconds("00:00:00.000")
        assert result == 0.0

    def test_timestamp_to_seconds_minutes(self):
        """Test parsing timestamp with minutes."""
        result = timestamp_to_seconds("00:02:05.500")
        assert abs(result - 125.5) < 0.001

    def test_timestamp_to_seconds_hours(self):
        """Test parsing timestamp with hours."""
        result = timestamp_to_seconds("01:01:01.123")
        assert abs(result - 3661.123) < 0.001

    def test_timestamp_to_seconds_short_format(self):
        """Test parsing short format timestamp (MM:SS.mmm)."""
        result = timestamp_to_seconds("02:05.500")
        assert abs(result - 125.5) < 0.001

    def test_timestamp_to_seconds_invalid_format(self):
        """Test parsing invalid timestamp format."""
        with pytest.raises(VttTimestampError):
            timestamp_to_seconds("invalid")

    def test_timestamp_roundtrip(self):
        """Test converting back and forth."""
        original = 3661.123
        timestamp = seconds_to_timestamp(original)
        back = timestamp_to_seconds(timestamp)
        assert abs(original - back) < 0.001


class TestMergeSegments:
    """Test segment merging functionality."""

    def test_merge_segments_no_merge_needed(self):
        """Test when segments don't need merging."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First"},
            {"start": 5.0, "end": 7.0, "text": "Second"},
        ]
        result = merge_segments(segments, gap_threshold=0.5)
        assert len(result) == 2

    def test_merge_segments_adjacent(self):
        """Test merging adjacent segments."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First"},
            {"start": 2.0, "end": 4.0, "text": "Second"},
        ]
        result = merge_segments(segments, gap_threshold=0.5)
        assert len(result) == 1
        assert result[0]["text"] == "First Second"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 4.0

    def test_merge_segments_small_gap(self):
        """Test merging with small gap."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First"},
            {"start": 2.3, "end": 4.0, "text": "Second"},
        ]
        result = merge_segments(segments, gap_threshold=0.5)
        assert len(result) == 1
        assert result[0]["text"] == "First Second"

    def test_merge_segments_multiple(self):
        """Test merging multiple segments."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "One"},
            {"start": 1.0, "end": 2.0, "text": "Two"},
            {"start": 2.0, "end": 3.0, "text": "Three"},
            {"start": 10.0, "end": 11.0, "text": "Four"},
        ]
        result = merge_segments(segments, gap_threshold=0.5)
        assert len(result) == 2
        assert result[0]["text"] == "One Two Three"
        assert result[1]["text"] == "Four"

    def test_merge_segments_preserves_ids(self):
        """Test that merged segments get new IDs."""
        segments = [
            {"id": 10, "start": 0.0, "end": 2.0, "text": "First"},
            {"id": 20, "start": 2.0, "end": 4.0, "text": "Second"},
        ]
        result = merge_segments(segments, gap_threshold=0.5)
        assert len(result) == 1
        # ID should be reset to sequential
        assert result[0]["id"] == 1

    def test_merge_segments_empty_list(self):
        """Test merging empty list."""
        result = merge_segments([], gap_threshold=0.5)
        assert result == []

    def test_merge_segments_single(self):
        """Test merging single segment."""
        segments = [{"start": 0.0, "end": 2.0, "text": "Only"}]
        result = merge_segments(segments, gap_threshold=0.5)
        assert len(result) == 1
        assert result[0]["text"] == "Only"


class TestSplitLongSegments:
    """Test segment splitting functionality."""

    def test_split_short_segment(self):
        """Test that short segments aren't split."""
        segments = [{"start": 0.0, "end": 2.0, "text": "Short text"}]
        result = split_long_segments(segments, max_chars=50)
        assert len(result) == 1
        assert result[0]["text"] == "Short text"

    def test_split_long_segment(self):
        """Test splitting a long segment."""
        long_text = "This is a very long segment that needs to be split into multiple parts for better readability"
        segments = [{"start": 0.0, "end": 10.0, "text": long_text}]
        result = split_long_segments(segments, max_chars=30)
        assert len(result) > 1
        # Check all text is preserved
        combined_text = " ".join(seg["text"] for seg in result)
        assert combined_text == long_text

    def test_split_preserves_timing(self):
        """Test that timing is distributed proportionally."""
        segments = [{"start": 0.0, "end": 10.0, "text": "Word1 Word2 Word3 Word4"}]
        result = split_long_segments(segments, max_chars=10)
        # Should split into multiple segments
        assert len(result) >= 2
        # First segment should start at 0.0
        assert result[0]["start"] == 0.0
        # Last segment should end at 10.0
        assert result[-1]["end"] == 10.0
        # Segments should be continuous
        for i in range(len(result) - 1):
            assert result[i]["end"] == result[i + 1]["start"]

    def test_split_multiple_segments(self):
        """Test splitting multiple segments."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Short"},
            {"start": 5.0, "end": 15.0, "text": "This is a longer segment that needs splitting"},
        ]
        result = split_long_segments(segments, max_chars=20)
        assert len(result) >= 3  # At least: 1 short + 2+ split

    def test_split_assigns_new_ids(self):
        """Test that split segments get sequential IDs."""
        segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 10.0,
                "text": "Long text that needs to be split into parts",
            }
        ]
        result = split_long_segments(segments, max_chars=15)
        # Check IDs are sequential
        for i, seg in enumerate(result):
            assert seg["id"] == i + 1

    def test_split_empty_list(self):
        """Test splitting empty list."""
        result = split_long_segments([], max_chars=50)
        assert result == []

    def test_split_respects_word_boundaries(self):
        """Test that splits occur at word boundaries."""
        segments = [{"start": 0.0, "end": 10.0, "text": "Hello world this is test"}]
        result = split_long_segments(segments, max_chars=12)
        # Each segment text should be complete words
        for seg in result:
            # Should not end with partial words
            assert not seg["text"].endswith(" ")
            assert seg["text"].strip() == seg["text"]


class TestShiftTimestamps:
    """Test timestamp shifting functionality."""

    def test_shift_timestamps_positive(self):
        """Test shifting timestamps forward."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First"},
            {"start": 2.0, "end": 4.0, "text": "Second"},
        ]
        result = shift_timestamps(segments, offset_seconds=10.0)
        assert result[0]["start"] == 10.0
        assert result[0]["end"] == 12.0
        assert result[1]["start"] == 12.0
        assert result[1]["end"] == 14.0

    def test_shift_timestamps_negative(self):
        """Test shifting timestamps backward."""
        segments = [
            {"start": 10.0, "end": 12.0, "text": "First"},
            {"start": 12.0, "end": 14.0, "text": "Second"},
        ]
        result = shift_timestamps(segments, offset_seconds=-5.0)
        assert result[0]["start"] == 5.0
        assert result[0]["end"] == 7.0

    def test_shift_timestamps_preserves_text(self):
        """Test that text is preserved during shift."""
        segments = [{"start": 0.0, "end": 2.0, "text": "Keep this"}]
        result = shift_timestamps(segments, offset_seconds=5.0)
        assert result[0]["text"] == "Keep this"

    def test_shift_timestamps_preserves_ids(self):
        """Test that IDs are preserved during shift."""
        segments = [{"id": 42, "start": 0.0, "end": 2.0, "text": "Test"}]
        result = shift_timestamps(segments, offset_seconds=5.0)
        assert result[0]["id"] == 42

    def test_shift_timestamps_empty_list(self):
        """Test shifting empty list."""
        result = shift_timestamps([], offset_seconds=10.0)
        assert result == []

    def test_shift_timestamps_zero_offset(self):
        """Test shifting with zero offset."""
        segments = [{"start": 1.0, "end": 3.0, "text": "Test"}]
        result = shift_timestamps(segments, offset_seconds=0.0)
        assert result[0]["start"] == 1.0
        assert result[0]["end"] == 3.0


class TestFilterSegmentsByTime:
    """Test time-based segment filtering."""

    def test_filter_within_range(self):
        """Test filtering segments within time range."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First"},
            {"start": 5.0, "end": 7.0, "text": "Second"},
            {"start": 10.0, "end": 12.0, "text": "Third"},
        ]
        result = filter_segments_by_time(segments, start_time=4.0, end_time=8.0)
        assert len(result) == 1
        assert result[0]["text"] == "Second"

    def test_filter_overlapping_start(self):
        """Test segment overlapping filter start."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Overlaps start"},
            {"start": 10.0, "end": 15.0, "text": "After"},
        ]
        result = filter_segments_by_time(segments, start_time=3.0, end_time=20.0)
        # Should include segment that overlaps
        assert len(result) == 2

    def test_filter_overlapping_end(self):
        """Test segment overlapping filter end."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Before"},
            {"start": 10.0, "end": 15.0, "text": "Overlaps end"},
        ]
        result = filter_segments_by_time(segments, start_time=0.0, end_time=12.0)
        assert len(result) == 2

    def test_filter_no_matches(self):
        """Test filtering with no matching segments."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Too early"},
            {"start": 100.0, "end": 102.0, "text": "Too late"},
        ]
        result = filter_segments_by_time(segments, start_time=10.0, end_time=20.0)
        assert len(result) == 0

    def test_filter_all_match(self):
        """Test filtering where all segments match."""
        segments = [
            {"start": 5.0, "end": 7.0, "text": "First"},
            {"start": 8.0, "end": 10.0, "text": "Second"},
        ]
        result = filter_segments_by_time(segments, start_time=0.0, end_time=20.0)
        assert len(result) == 2

    def test_filter_empty_list(self):
        """Test filtering empty list."""
        result = filter_segments_by_time([], start_time=0.0, end_time=10.0)
        assert result == []

    def test_filter_preserves_segment_data(self):
        """Test that filtered segments preserve all data."""
        segments = [{"id": 5, "start": 1.0, "end": 3.0, "text": "Keep me"}]
        result = filter_segments_by_time(segments, start_time=0.0, end_time=10.0)
        assert result[0]["id"] == 5
        assert result[0]["text"] == "Keep me"


class TestGetSegmentsStats:
    """Test statistics calculation functionality."""

    def test_stats_basic(self):
        """Test basic statistics calculation."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello world"},
            {"start": 2.0, "end": 5.0, "text": "This is a test"},
        ]
        stats = get_segments_stats(segments)
        assert stats["num_segments"] == 2
        assert stats["total_duration"] == 5.0
        assert stats["total_chars"] == 25  # "Hello world" (11) + "This is a test" (14)
        assert stats["total_words"] == 6  # "Hello world This is a test"

    def test_stats_empty(self):
        """Test statistics for empty segments."""
        stats = get_segments_stats([])
        assert stats["num_segments"] == 0
        assert stats["total_duration"] == 0.0
        assert stats["total_chars"] == 0
        assert stats["total_words"] == 0

    def test_stats_single_segment(self):
        """Test statistics for single segment."""
        segments = [{"start": 10.0, "end": 15.0, "text": "Five seconds long"}]
        stats = get_segments_stats(segments)
        assert stats["num_segments"] == 1
        assert stats["total_duration"] == 5.0
        assert stats["total_words"] == 3

    def test_stats_average_calculations(self):
        """Test average calculations."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Short"},
            {"start": 2.0, "end": 6.0, "text": "Longer segment here"},
        ]
        stats = get_segments_stats(segments)
        assert stats["avg_duration"] == 3.0  # (2 + 4) / 2
        # Average chars: (5 + 19) / 2 = 12
        assert stats["avg_chars_per_segment"] == 12.0

    def test_stats_words_per_second(self):
        """Test words per second calculation."""
        segments = [
            {"start": 0.0, "end": 60.0, "text": "One two three four five six seven eight nine ten"},
        ]
        stats = get_segments_stats(segments)
        # 10 words in 60 seconds = 0.1666... words per second
        assert abs(stats["words_per_second"] - (10.0 / 60.0)) < 0.001

    def test_stats_avg_words_per_segment(self):
        """Test average words per segment calculation."""
        segments = [
            {"start": 0.0, "end": 10.0, "text": "One two three four five"},  # 5 words
            {"start": 10.0, "end": 20.0, "text": "Six seven eight nine ten"},  # 5 words
        ]
        stats = get_segments_stats(segments)
        assert stats["avg_words_per_segment"] == 5.0

    def test_stats_with_gaps(self):
        """Test statistics with gaps between segments."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First"},
            {"start": 10.0, "end": 12.0, "text": "Second"},
        ]
        stats = get_segments_stats(segments)
        # Total duration should be calculated correctly despite gaps
        assert stats["total_duration"] == 4.0  # 2 + 2, not 12


class TestRemoveFillerWords:
    """Test filler word removal for podcast transcriptions."""

    def test_remove_default_fillers(self):
        """Test removing default filler words."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Um so basically I think"},
            {"start": 2.0, "end": 4.0, "text": "You know like it's actually good"},
        ]
        result = remove_filler_words(segments)
        assert result[0]["text"] == "so I think"
        assert result[1]["text"] == "it's good"

    def test_remove_custom_fillers(self):
        """Test removing custom filler words."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Well the thing is very interesting"},
        ]
        result = remove_filler_words(segments, fillers=["well", "the thing is"])
        assert result[0]["text"] == "very interesting"

    def test_preserve_timing(self):
        """Test that timing is preserved."""
        segments = [
            {"id": 5, "start": 10.0, "end": 12.0, "text": "Um hello"},
        ]
        result = remove_filler_words(segments, preserve_timing=True)
        assert result[0]["start"] == 10.0
        assert result[0]["end"] == 12.0
        assert result[0]["id"] == 5

    def test_case_insensitive_removal(self):
        """Test filler removal is case-insensitive."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "UM UH LIKE hello"},
        ]
        result = remove_filler_words(segments)
        assert result[0]["text"] == "hello"

    def test_empty_segment_handling(self):
        """Test handling segments that become empty."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "um uh"},
            {"start": 2.0, "end": 4.0, "text": "Hello world"},
        ]
        result = remove_filler_words(segments, preserve_timing=False)
        # Empty segment should be removed
        assert len(result) == 1
        assert result[0]["text"] == "Hello world"

    def test_preserve_speaker_info(self):
        """Test that speaker info is preserved."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Um hello", "speaker": "Alice"},
        ]
        result = remove_filler_words(segments)
        assert result[0]["speaker"] == "Alice"

    def test_empty_segments_list(self):
        """Test with empty segments list."""
        result = remove_filler_words([])
        assert result == []


class TestGroupBySpeaker:
    """Test speaker diarization grouping."""

    def test_group_same_speaker(self):
        """Test grouping consecutive same-speaker segments."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker": "Alice"},
            {"start": 1.0, "end": 2.0, "text": "world", "speaker": "Alice"},
            {"start": 2.0, "end": 3.0, "text": "test", "speaker": "Alice"},
        ]
        result = group_by_speaker(segments)
        assert len(result) == 1
        assert result[0]["text"] == "<v Alice>Hello world test"
        assert result[0]["speaker"] == "Alice"

    def test_group_different_speakers(self):
        """Test grouping with speaker changes."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker": "Alice"},
            {"start": 1.0, "end": 2.0, "text": "Hi there", "speaker": "Bob"},
            {"start": 2.0, "end": 3.0, "text": "How are you", "speaker": "Alice"},
        ]
        result = group_by_speaker(segments)
        assert len(result) == 3
        assert "<v Alice>Hello" in result[0]["text"]
        assert "<v Bob>Hi there" in result[1]["text"]
        assert "<v Alice>How are you" in result[2]["text"]

    def test_group_with_gap_threshold(self):
        """Test that large gaps break grouping."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker": "Alice"},
            {"start": 10.0, "end": 11.0, "text": "World", "speaker": "Alice"},
        ]
        result = group_by_speaker(segments, max_gap=2.0)
        assert len(result) == 2  # Gap too large, not merged

    def test_format_speaker_disabled(self):
        """Test without speaker formatting."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker": "Alice"},
            {"start": 1.0, "end": 2.0, "text": "world", "speaker": "Alice"},
        ]
        result = group_by_speaker(segments, format_speaker=False)
        assert result[0]["text"] == "Hello world"
        assert "<v" not in result[0]["text"]

    def test_unknown_speaker(self):
        """Test handling missing speaker field."""
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.0, "end": 2.0, "text": "world"},
        ]
        result = group_by_speaker(segments)
        assert len(result) == 1
        assert "Unknown" in result[0]["text"]

    def test_empty_segments_list(self):
        """Test with empty segments list."""
        result = group_by_speaker([])
        assert result == []


class TestFilterByConfidence:
    """Test confidence-based filtering."""

    def test_filter_low_confidence(self):
        """Test removing low confidence segments."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "High", "confidence": 0.95},
            {"start": 2.0, "end": 4.0, "text": "Low", "confidence": 0.5},
            {"start": 4.0, "end": 6.0, "text": "Medium", "confidence": 0.85},
        ]
        result = filter_by_confidence(segments, min_confidence=0.8)
        assert len(result) == 2
        assert result[0]["text"] == "High"
        assert result[1]["text"] == "Medium"

    def test_mark_low_confidence(self):
        """Test marking instead of removing low confidence segments."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "High", "confidence": 0.95},
            {"start": 2.0, "end": 4.0, "text": "Low", "confidence": 0.5},
        ]
        result = filter_by_confidence(segments, min_confidence=0.8, remove_or_mark="mark")
        assert len(result) == 2
        assert "low_confidence" not in result[0]
        assert result[1]["low_confidence"] is True

    def test_assume_high_confidence_when_missing(self):
        """Test assuming high confidence when field is missing."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "No confidence field"},
        ]
        result = filter_by_confidence(segments, min_confidence=0.8)
        assert len(result) == 1

    def test_preserves_confidence_in_output(self):
        """Test that confidence is preserved in output."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Test", "confidence": 0.92},
        ]
        result = filter_by_confidence(segments, min_confidence=0.8)
        assert result[0]["confidence"] == 0.92

    def test_preserves_speaker_info(self):
        """Test that speaker info is preserved."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Test", "confidence": 0.9, "speaker": "Bob"},
        ]
        result = filter_by_confidence(segments)
        assert result[0]["speaker"] == "Bob"

    def test_empty_segments_list(self):
        """Test with empty segments list."""
        result = filter_by_confidence([])
        assert result == []


class TestWordsToSegments:
    """Test word-level to segment-level aggregation."""

    def test_basic_word_aggregation(self):
        """Test basic word aggregation."""
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world.", "start": 0.6, "end": 1.0},
            {"word": "How", "start": 1.5, "end": 1.8},
            {"word": "are", "start": 1.9, "end": 2.1},
            {"word": "you?", "start": 2.2, "end": 2.5},
        ]
        result = words_to_segments(words)
        # Should create segments based on punctuation
        assert len(result) >= 2
        # First segment should contain at least "Hello"
        assert "Hello" in result[0]["text"]
        # Verify segments are created
        all_text = " ".join(seg["text"] for seg in result)
        assert "Hello" in all_text
        assert "world." in all_text
        assert "you?" in all_text

    def test_pause_threshold_breaks(self):
        """Test that long pauses break segments."""
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 1.0},
            {"word": "test", "start": 5.0, "end": 5.5},  # Long pause
        ]
        result = words_to_segments(words, pause_threshold=1.0)
        assert len(result) >= 2

    def test_max_duration_limit(self):
        """Test maximum segment duration limit."""
        words = [{"word": f"word{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(30)]
        result = words_to_segments(words, max_segment_duration=5.0)
        # Should have multiple segments due to duration limit
        assert len(result) > 1
        # Check each segment doesn't exceed max duration
        for seg in result:
            assert seg["end"] - seg["start"] <= 6.0  # Some tolerance

    def test_supports_text_field(self):
        """Test that 'text' field works as alternative to 'word'."""
        words = [
            {"text": "Hello", "start": 0.0, "end": 0.5},
            {"text": "world", "start": 0.6, "end": 1.0},
        ]
        result = words_to_segments(words)
        assert len(result) >= 1
        assert "Hello" in result[0]["text"]

    def test_empty_words_list(self):
        """Test with empty words list."""
        result = words_to_segments([])
        assert result == []


class TestRemoveRepeatedPhrases:
    """Test repeated phrase removal."""

    def test_remove_single_word_repetition(self):
        """Test removing single word repetitions."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "the the the quick brown fox"},
        ]
        result = remove_repeated_phrases(segments)
        assert result[0]["text"] == "the quick brown fox"

    def test_remove_multi_word_repetition(self):
        """Test removing multi-word phrase repetitions."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "I think I think I think it's good"},
        ]
        result = remove_repeated_phrases(segments, min_repetitions=2)
        assert result[0]["text"] == "I think it's good"

    def test_preserve_non_repeated(self):
        """Test that non-repeated text is preserved."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello world this is a test"},
        ]
        result = remove_repeated_phrases(segments)
        assert result[0]["text"] == "Hello world this is a test"

    def test_case_insensitive_matching(self):
        """Test case-insensitive repetition matching."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello HELLO hello world"},
        ]
        result = remove_repeated_phrases(segments)
        assert result[0]["text"] == "Hello world"

    def test_preserves_segment_info(self):
        """Test that segment info is preserved."""
        segments = [
            {"id": 5, "start": 10.0, "end": 12.0, "text": "test test", "speaker": "Alice"},
        ]
        result = remove_repeated_phrases(segments)
        assert result[0]["id"] == 5
        assert result[0]["start"] == 10.0
        assert result[0]["speaker"] == "Alice"

    def test_empty_segments_list(self):
        """Test with empty segments list."""
        result = remove_repeated_phrases([])
        assert result == []


class TestDetectChapters:
    """Test automatic chapter detection."""

    def test_detect_chapter_by_silence(self):
        """Test detecting chapters by long silence."""
        segments = [
            {"start": 0.0, "end": 30.0, "text": "Chapter 1 content"},
            {"start": 31.0, "end": 90.0, "text": "More chapter 1"},  # Long segment
            {"start": 100.0, "end": 130.0, "text": "Chapter 2 content"},  # 10s gap
            {"start": 131.0, "end": 160.0, "text": "More chapter 2"},
        ]
        result = detect_chapters(segments, min_chapter_duration=60.0, silence_threshold=5.0)
        assert len(result) >= 2
        assert result[0]["chapter"] == 1
        assert result[0]["start"] == 0.0
        # Second chapter should start at 100.0 (after the gap)
        assert result[1]["chapter"] == 2
        assert result[1]["start"] == 100.0

    def test_first_chapter_always_exists(self):
        """Test that first chapter is always created."""
        segments = [
            {"start": 0.0, "end": 10.0, "text": "Content"},
        ]
        result = detect_chapters(segments)
        assert len(result) >= 1
        assert result[0]["chapter"] == 1
        assert result[0]["start"] == 0.0

    def test_timestamp_formatting(self):
        """Test that timestamps are formatted correctly."""
        segments = [
            {"start": 3661.0, "end": 3700.0, "text": "Content"},
        ]
        result = detect_chapters(segments)
        assert result[0]["timestamp"] == "01:01:01"

    def test_min_chapter_duration_respected(self):
        """Test minimum chapter duration is respected."""
        segments = [
            {"start": 0.0, "end": 10.0, "text": "Short 1"},
            {"start": 20.0, "end": 30.0, "text": "Short 2"},  # 10s gap but chapter too short
        ]
        result = detect_chapters(segments, min_chapter_duration=60.0, silence_threshold=5.0)
        # Should not create new chapter since minimum duration not met
        assert len(result) == 1

    def test_empty_segments_list(self):
        """Test with empty segments list."""
        result = detect_chapters([])
        assert result == []


class TestParseVttString:
    def test_basic_parse(self):
        vtt = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.500\nHello world\n\n2\n00:00:02.500 --> 00:00:05.000\nThis is a test\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.5
        assert result[0]["text"] == "Hello world"
        assert result[1]["id"] == 2
        assert result[1]["start"] == 2.5
        assert result[1]["end"] == 5.0
        assert result[1]["text"] == "This is a test"

    def test_without_cue_identifiers(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nHello world\n\n00:00:02.500 --> 00:00:05.000\nSecond cue\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 2
        assert result[0]["text"] == "Hello world"
        assert result[1]["text"] == "Second cue"

    def test_short_timestamp_format(self):
        vtt = "WEBVTT\n\n00:00.000 --> 00:02.500\nShort format\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.5

    def test_multiline_cue_text(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nLine one\nLine two\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1
        assert result[0]["text"] == "Line one\nLine two"

    def test_unescape_entities(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nTom &amp; Jerry &lt;3\n"
        result = parse_vtt_string(vtt)
        assert result[0]["text"] == "Tom & Jerry <3"

    def test_unescape_disabled(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nTom &amp; Jerry\n"
        result = parse_vtt_string(vtt, unescape=False)
        assert result[0]["text"] == "Tom &amp; Jerry"

    def test_skips_note_blocks(self):
        vtt = "WEBVTT\n\nNOTE This is a comment\nspanning multiple lines\n\n00:00:00.000 --> 00:00:02.500\nActual cue\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1
        assert result[0]["text"] == "Actual cue"

    def test_skips_style_blocks(self):
        vtt = "WEBVTT\n\nSTYLE\n::cue { color: white; }\n\n00:00:00.000 --> 00:00:02.500\nStyled cue\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1
        assert result[0]["text"] == "Styled cue"

    def test_header_with_description(self):
        vtt = "WEBVTT - My Description\n\n00:00:00.000 --> 00:00:02.500\nHello\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1

    def test_header_with_metadata(self):
        vtt = "WEBVTT\nKind: captions\nLanguage: en\n\n00:00:00.000 --> 00:00:02.500\nHello\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1

    def test_invalid_header(self):
        vtt = "NOT A VTT FILE\n\n00:00:00.000 --> 00:00:02.500\nHello\n"
        with pytest.raises(VttHeaderError):
            parse_vtt_string(vtt)

    def test_empty_input(self):
        with pytest.raises(VttHeaderError):
            parse_vtt_string("")

    def test_sequential_ids(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nFirst\n\n00:00:01.000 --> 00:00:02.000\nSecond\n\n00:00:02.000 --> 00:00:03.000\nThird\n"
        result = parse_vtt_string(vtt)
        assert [s["id"] for s in result] == [1, 2, 3]

    def test_cue_settings_ignored(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500 position:50% align:center\nPositioned cue\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1
        assert result[0]["end"] == 2.5

    def test_bom_header(self):
        vtt = "\ufeffWEBVTT\n\n00:00:00.000 --> 00:00:02.500\nBOM test\n"
        result = parse_vtt_string(vtt)
        assert len(result) == 1


class TestParseVttFile:
    def test_basic_parse(self):
        vtt_content = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.500\nHello world\n\n2\n00:00:02.500 --> 00:00:05.000\nThis is a test\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write(vtt_content)
            f.flush()
            result = parse_vtt_file(f.name)
        os.unlink(f.name)
        assert len(result) == 2
        assert result[0]["text"] == "Hello world"
        assert result[1]["text"] == "This is a test"

    def test_file_not_found(self):
        with pytest.raises(IOError):
            parse_vtt_file("/nonexistent/path.vtt")

    def test_roundtrip(self):
        segments = [
            {"id": 1, "start": 0.0, "end": 2.5, "text": "Hello world"},
            {"id": 2, "start": 2.5, "end": 5.0, "text": "This is a test"},
        ]
        vtt_output = build_vtt_string(segments)
        result = parse_vtt_string(vtt_output)
        assert len(result) == 2
        assert result[0]["start"] == segments[0]["start"]
        assert result[0]["end"] == segments[0]["end"]
        assert result[0]["text"] == segments[0]["text"]
        assert result[1]["start"] == segments[1]["start"]
        assert result[1]["end"] == segments[1]["end"]
        assert result[1]["text"] == segments[1]["text"]

    def test_roundtrip_with_escaping(self):
        segments = [
            {"id": 1, "start": 0.0, "end": 2.5, "text": "Tom & Jerry <3"},
        ]
        vtt_output = build_vtt_string(segments, escape_text=True)
        result = parse_vtt_string(vtt_output, unescape=True)
        assert result[0]["text"] == "Tom & Jerry <3"


class TestValidateCueSequence:
    """Cross-cue sequence validation: ordering, overlap, gaps, duration bounds.

    These duplicate the Rust unit tests in src/lib.rs deliberately. The crate is
    cdylib-only with pyo3's extension-module feature, so `cargo test` cannot link
    and the Rust tests never execute; this layer is what actually verifies the
    behavior.
    """

    def test_ordered_disjoint_sequence_passes(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 3.0, "end": 5.0, "text": "Two"},
            {"start": 6.0, "end": 8.0, "text": "Three"},
        ]
        assert validate_cue_sequence(segments) is True

    def test_overlapping_pair_rejected(self):
        """The silent-corruption case this whole feature exists to surface."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(segments)

    def test_out_of_order_pair_rejected(self):
        segments = [
            {"start": 10.0, "end": 12.0, "text": "Later"},
            {"start": 2.0, "end": 4.0, "text": "Earlier"},
        ]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(segments)

    def test_exact_abutment_passes(self):
        """Normal chunker output; rejecting it would fail every good transcript."""
        segments = [
            {"start": 0.0, "end": 2.5, "text": "One"},
            {"start": 2.5, "end": 5.0, "text": "Two"},
        ]
        assert validate_cue_sequence(segments) is True

    def test_zero_length_cue_rejected(self):
        segments = [{"start": 1.0, "end": 1.0, "text": "Never displayed"}]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(segments)

    def test_empty_and_single_lists_pass(self):
        """No cue pair exists, so no pair can conflict."""
        assert validate_cue_sequence([]) is True
        assert validate_cue_sequence([{"start": 0.0, "end": 2.0, "text": "Solo"}]) is True

    def test_gap_below_minimum_rejected(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 2.05, "end": 4.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(segments, min_gap=0.1)

    def test_gap_meeting_minimum_passes(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 2.2, "end": 4.0, "text": "Two"},
        ]
        assert validate_cue_sequence(segments, min_gap=0.1) is True

    def test_abutting_cues_pass_without_min_gap(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 2.0, "end": 4.0, "text": "Two"},
        ]
        assert validate_cue_sequence(segments) is True

    def test_cue_ending_after_duration_rejected(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 3.0, "end": 12.0, "text": "Overruns"},
        ]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(segments, audio_duration=10.0)

    def test_cue_starting_past_duration_rejected(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 11.0, "end": 12.0, "text": "Past the end"},
        ]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(segments, audio_duration=10.0)

    def test_cues_within_duration_pass(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 3.0, "end": 10.0, "text": "Ends exactly at duration"},
        ]
        assert validate_cue_sequence(segments, audio_duration=10.0) is True

    def test_error_message_locates_the_bad_pair(self):
        """A failure must be actionable from a log line alone."""
        segments = [
            {"id": 7, "start": 0.0, "end": 5.0, "text": "One"},
            {"id": 8, "start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError) as exc_info:
            validate_cue_sequence(segments)

        message = str(exc_info.value)
        assert "7" in message, message
        assert "8" in message, message
        assert "3" in message, message
        assert "5" in message, message


class TestCueSequenceQuantization:
    """Comparisons happen at millisecond precision, not on raw floats.

    These pin the decision to quantize: without them a refactor back to f64
    comparison would pass the suite while making exact abutment depend on
    whichever arithmetic produced each timestamp.
    """

    def test_abutment_survives_floating_point_arithmetic(self):
        """0.1 * 3 is 0.30000000000000004, but both quantize to 300ms."""
        drifted_end = 0.1 + 0.1 + 0.1
        assert drifted_end != 0.3  # the drift is real
        segments = [
            {"start": 0.0, "end": drifted_end, "text": "One"},
            {"start": 0.3, "end": 1.0, "text": "Two"},
        ]
        assert validate_cue_sequence(segments) is True

    def test_sub_millisecond_overlap_ignored(self):
        """An overlap too small to serialize cannot affect a player."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 1.9999, "end": 4.0, "text": "Two"},
        ]
        assert validate_cue_sequence(segments) is True

    def test_cue_zero_length_only_after_quantization_rejected(self):
        """Spans 0.0001s, which serializes to a zero-length cue."""
        segments = [{"start": 1.0, "end": 1.0001, "text": "Vanishes"}]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(segments)

    def test_min_gap_zero_admits_abutting_cues(self):
        """Gap comparison is strictly less-than."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 2.0, "end": 4.0, "text": "Two"},
        ]
        assert validate_cue_sequence(segments, min_gap=0.0) is True

    def test_quantization_agrees_with_written_timestamps(self):
        """The validator must agree with the write path about what a time is."""
        boundary = 2.0004
        assert seconds_to_timestamp(boundary) == "00:00:02.000"
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": boundary, "end": 4.0, "text": "Two"},
        ]
        assert validate_cue_sequence(segments) is True

    def test_long_duration_timestamps_compare_correctly(self):
        """Float spacing grows with magnitude; quantization must not drift.

        A fixed epsilon would behave differently here than near zero, which is
        the reason milliseconds were chosen over an epsilon.
        """
        segments = [
            {"start": 7200.0, "end": 7202.5, "text": "Two hours in"},
            {"start": 7202.5, "end": 7205.0, "text": "Abuts exactly"},
        ]
        assert validate_cue_sequence(segments) is True

        overlapping = [
            {"start": 7200.0, "end": 7205.0, "text": "Two hours in"},
            {"start": 7202.5, "end": 7207.0, "text": "Overlaps"},
        ]
        with pytest.raises(VttSequenceError):
            validate_cue_sequence(overlapping)


class TestSequenceErrorHierarchy:
    """VttSequenceError must be distinguishable but still broadly catchable."""

    def test_caught_by_validation_error(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttValidationError):
            validate_cue_sequence(segments)

    def test_caught_by_base_error(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttError):
            validate_cue_sequence(segments)

    def test_sequence_error_is_a_subclass_of_validation_error(self):
        assert issubclass(VttSequenceError, VttValidationError)
        assert issubclass(VttSequenceError, VttError)

    def test_single_cue_faults_do_not_raise_sequence_error(self):
        """A per-cue fault must stay distinguishable from a sequence fault."""
        negative = [{"start": -1.0, "end": 2.0, "text": "Negative"}]
        with pytest.raises(VttTimestampError):
            validate_segments(negative)
        assert not issubclass(VttTimestampError, VttSequenceError)

        empty_text = [{"start": 0.0, "end": 2.0, "text": "   "}]
        with pytest.raises(VttCueError):
            validate_segments(empty_text)
        assert not issubclass(VttCueError, VttSequenceError)

    def test_sequence_fault_not_caught_by_per_cue_error_types(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError):
            try:
                validate_cue_sequence(segments)
            except (VttTimestampError, VttCueError):  # pragma: no cover
                pytest.fail("sequence fault raised a per-cue error type")


class TestBuildersRejectBadSequences:
    """Builders must not write a file whose cues are collectively malformed."""

    def test_file_builder_rejects_overlap(self, temp_output_file):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError):
            build_vtt_from_records(segments, temp_output_file)

    def test_no_file_left_behind_after_rejection(self, temp_output_file):
        """A failed build must not be mistakable for a successful one."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError):
            build_vtt_from_records(segments, temp_output_file)

        assert not os.path.exists(temp_output_file)

    def test_existing_file_survives_a_rejected_build(self, temp_output_file):
        """The case a caller is most likely to hit: rebuilding over a good file."""
        good = [
            {"start": 0.0, "end": 2.0, "text": "Original content"},
        ]
        build_vtt_from_records(good, temp_output_file)
        with open(temp_output_file) as f:
            original = f.read()

        bad = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError):
            build_vtt_from_records(bad, temp_output_file)

        with open(temp_output_file) as f:
            assert f.read() == original

    def test_no_temp_file_left_in_destination_directory(self, temp_output_file):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        directory = os.path.dirname(temp_output_file)
        before = set(os.listdir(directory))

        with pytest.raises(VttSequenceError):
            build_vtt_from_records(segments, temp_output_file)

        leftover = set(os.listdir(directory)) - before
        assert not leftover, f"temp files left behind: {leftover}"

    def test_string_builder_rejects_overlap(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        with pytest.raises(VttSequenceError):
            build_vtt_string(segments)

    def test_file_builder_opt_out_writes_overlap(self, temp_output_file):
        """validate_segments=False preserves the pre-0.6.0 behavior exactly."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        build_vtt_from_records(segments, temp_output_file, validate_segments=False)

        with open(temp_output_file) as f:
            content = f.read()
        assert "00:00:03.000 --> 00:00:07.000" in content

    def test_string_builder_opt_out_writes_overlap(self):
        """Note this builder names its flag `validate`, not `validate_segments`."""
        segments = [
            {"start": 0.0, "end": 5.0, "text": "One"},
            {"start": 3.0, "end": 7.0, "text": "Two"},
        ]
        result = build_vtt_string(segments, validate=False)
        assert "00:00:03.000 --> 00:00:07.000" in result

    def test_valid_sequence_still_builds_unchanged(self, temp_output_file):
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Hello world"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "This is a test"},
        ]
        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file) as f:
            content = f.read()
        assert "WEBVTT" in content
        assert "1\n00:00:00.000 --> 00:00:02.000\nHello world" in content
        assert "2\n00:00:02.000 --> 00:00:04.000\nThis is a test" in content

    def test_json_files_builder_does_not_check_cross_file_ordering(self, temp_output_file):
        """Documented limit: it streams files and never sees the whole sequence.

        Pinned so it cannot be "fixed" into a half-guarantee that covers only
        within-file ordering — cross-file boundaries are where a bad offset
        actually shows up.
        """
        first = {
            "transcript": "First",
            "segments": [{"id": 1, "start": 0.0, "end": 9.0, "text": "First file"}],
        }
        second = {
            "transcript": "Second",
            "segments": [{"id": 1, "start": 0.0, "end": 3.0, "text": "Second file"}],
        }

        paths = []
        for payload in (first, second):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(payload, f)
                paths.append(f.name)

        try:
            build_vtt_from_json_files(paths, temp_output_file)
            assert os.path.exists(temp_output_file)
        finally:
            for path in paths:
                os.unlink(path)


class TestClampToDuration:
    """Bounding cues to a media duration, so callers can correct not just detect."""

    def test_overrunning_cue_is_truncated(self):
        segments = [{"start": 2.0, "end": 9.0, "text": "Overruns"}]
        result = clamp_to_duration(segments, 5.0)

        assert len(result) == 1
        assert result[0]["start"] == 2.0
        assert result[0]["end"] == 5.0

    def test_cue_starting_past_duration_is_dropped(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Kept"},
            {"start": 12.0, "end": 14.0, "text": "Dropped"},
        ]
        result = clamp_to_duration(segments, 5.0)

        assert len(result) == 1
        assert result[0]["text"] == "Kept"

    def test_cue_starting_exactly_at_duration_is_dropped(self):
        segments = [{"start": 5.0, "end": 7.0, "text": "At the boundary"}]
        assert clamp_to_duration(segments, 5.0) == []

    def test_in_range_cues_are_unchanged(self):
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "One"},
            {"id": 2, "start": 2.5, "end": 4.0, "text": "Two"},
        ]
        result = clamp_to_duration(segments, 10.0)

        assert len(result) == 2
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0
        assert result[1]["start"] == 2.5
        assert result[1]["end"] == 4.0

    def test_ids_are_renumbered_sequentially(self):
        segments = [
            {"id": 5, "start": 0.0, "end": 2.0, "text": "One"},
            {"id": 9, "start": 2.5, "end": 4.0, "text": "Two"},
        ]
        result = clamp_to_duration(segments, 10.0)
        assert [seg["id"] for seg in result] == [1, 2]

    def test_extra_keys_are_dropped(self):
        """Matches merge_segments: no transformation preserves extra keys."""
        segments = [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "One",
                "speaker": "Alice",
                "confidence": 0.9,
            }
        ]
        result = clamp_to_duration(segments, 10.0)

        assert set(result[0].keys()) == {"id", "start", "end", "text"}

    def test_empty_list_returns_empty(self):
        assert clamp_to_duration([], 10.0) == []

    def test_all_cues_past_duration_returns_empty(self):
        segments = [
            {"start": 20.0, "end": 22.0, "text": "One"},
            {"start": 23.0, "end": 25.0, "text": "Two"},
        ]
        assert clamp_to_duration(segments, 10.0) == []

    def test_clamped_output_passes_sequence_validation(self):
        """The round trip that makes this useful: clamp, then assert."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 2.5, "end": 4.0, "text": "Two"},
            {"start": 4.5, "end": 12.0, "text": "Overruns"},
            {"start": 15.0, "end": 17.0, "text": "Past the end"},
        ]
        clamped = clamp_to_duration(segments, 10.0)

        assert validate_cue_sequence(clamped, audio_duration=10.0) is True

    def test_clamped_output_builds_successfully(self):
        """Clamping is the documented fix for a duration-overrun rejection."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "One"},
            {"start": 2.5, "end": 12.0, "text": "Overruns"},
        ]
        clamped = clamp_to_duration(segments, 10.0)
        result = build_vtt_string(clamped)

        assert "WEBVTT" in result
        assert "00:00:02.500 --> 00:00:10.000" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
