import json
import os
import tempfile

import pytest
from vtt_builder import (
    build_transcript_from_json_files,
    build_vtt_from_json_files,
    build_vtt_from_records,
    validate_vtt_file,
    validate_segments,
    escape_vtt_text,
    unescape_vtt_text,
    VttError,
    VttValidationError,
    VttTimestampError,
    VttHeaderError,
    VttCueError,
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

    def test_build_vtt_from_json_files_single_file(
        self, temp_json_file, temp_output_file
    ):
        """Test building VTT from a single JSON file."""
        build_vtt_from_json_files([temp_json_file], temp_output_file)

        # Verify output file exists
        assert os.path.exists(temp_output_file)

        # Read and verify content
        with open(temp_output_file, "r") as f:
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
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(data, f)
                temp_files.append(f.name)

        try:
            build_vtt_from_json_files(temp_files, temp_output_file)

            with open(temp_output_file, "r") as f:
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
        with pytest.raises(Exception):  # Should raise IOError
            build_vtt_from_json_files(["/nonexistent/file.json"], temp_output_file)

    def test_build_vtt_from_json_files_invalid_json(self, temp_output_file):
        """Test error handling for invalid JSON."""
        # Create temp file with invalid JSON
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            temp_invalid = f.name

        try:
            with pytest.raises(Exception):  # Should raise ValueError
                build_vtt_from_json_files([temp_invalid], temp_output_file)
        finally:
            os.unlink(temp_invalid)

    def test_build_transcript_from_json_files_single_file(
        self, temp_json_file, temp_output_file
    ):
        """Test building transcript from a single JSON file."""
        build_transcript_from_json_files([temp_json_file], temp_output_file)

        assert os.path.exists(temp_output_file)

        with open(temp_output_file, "r") as f:
            content = f.read().strip()

        assert content == "Hello world. This is a test."

    def test_build_transcript_from_json_files_multiple_files(
        self, sample_transcript_data, sample_transcript_data_2, temp_output_file
    ):
        """Test building transcript from multiple JSON files."""
        temp_files = []
        for data in [sample_transcript_data, sample_transcript_data_2]:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(data, f)
                temp_files.append(f.name)

        try:
            build_transcript_from_json_files(temp_files, temp_output_file)

            with open(temp_output_file, "r") as f:
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

        with open(temp_output_file, "r") as f:
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

        with pytest.raises(Exception):  # Should raise KeyError
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

        with open(temp_output_file, "r") as f:
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
        with pytest.raises(Exception):  # Should raise IOError
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

        with open(temp_output_file, "r") as f:
            content = f.read()

        assert "Tom &amp; Jerry" in content
        assert "Use &lt;html&gt; tags" in content

    def test_build_vtt_can_disable_escaping(self, temp_output_file):
        """Test that escaping can be disabled."""
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "Tom & Jerry"},
        ]

        build_vtt_from_records(segments, temp_output_file, escape_text=False)

        with open(temp_output_file, "r") as f:
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
        build_vtt_from_records(
            invalid_segments, temp_output_file, validate_segments=False
        )
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
        with open(temp_output_file, "r", encoding="utf-8") as f:
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
        with open(temp_output_file, "r", encoding="utf-8") as f:
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
        with open(temp_output_file, "r", encoding="utf-8") as f:
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
        with open(temp_output_file, "r", encoding="utf-8") as f:
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
        with open(temp_output_file, "r", encoding="utf-8") as f:
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
        with open(temp_output_file, "r", encoding="utf-8") as f:
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
        with open(temp_output_file, "r", encoding="utf-8") as f:
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

        with open(temp_output_file, "r") as f:
            content = f.read()

        # Should still have WEBVTT header
        assert content.strip() == "WEBVTT"

    def test_single_segment(self, temp_output_file):
        """Test building VTT with a single segment."""
        segments = [{"id": 1, "start": 0.0, "end": 2.0, "text": "Only segment"}]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file, "r") as f:
            content = f.read()

        assert "WEBVTT" in content
        assert "1\n00:00:00.000 --> 00:00:02.000\nOnly segment" in content

    def test_zero_duration_segment(self, temp_output_file):
        """Test segment with zero duration."""
        segments = [{"id": 1, "start": 1.0, "end": 1.0, "text": "Zero duration"}]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file, "r") as f:
            content = f.read()

        assert "1\n00:00:01.000 --> 00:00:01.000\nZero duration" in content

    def test_large_timestamps(self, temp_output_file):
        """Test with large timestamp values."""
        segments = [
            {"id": 1, "start": 3661.5, "end": 3665.0, "text": "Large timestamp"}
        ]

        build_vtt_from_records(segments, temp_output_file)

        with open(temp_output_file, "r") as f:
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

        with open(temp_output_file, "r", encoding="utf-8") as f:
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
