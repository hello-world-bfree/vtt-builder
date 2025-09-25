import json
import os
import tempfile

import pytest
from vtt_builder._lowlevel import (
    build_transcript_from_json_files,
    build_vtt_from_json_files,
    build_vtt_from_records,
    validate_vtt_file,
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

        with pytest.raises(Exception):
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

        with pytest.raises(Exception):  # Should raise ValueError
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

        with pytest.raises(Exception):  # Should raise ValueError
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

        with pytest.raises(Exception):  # Should raise ValueError
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

        with pytest.raises(Exception):  # Should raise ValueError
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

        with pytest.raises(Exception):  # Should raise ValueError
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

        with pytest.raises(Exception):  # Should raise ValueError
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_missing_timing_after_identifier(self, temp_output_file):
        """Test validation fails when cue identifier is not followed by timing."""
        invalid_vtt = """WEBVTT

cue1
Hello world without timing
"""
        with open(temp_output_file, "w") as f:
            f.write(invalid_vtt)

        with pytest.raises(Exception):  # Should raise ValueError
            validate_vtt_file(temp_output_file)

    def test_validate_vtt_file_nonexistent(self):
        """Test validation fails for nonexistent file."""
        with pytest.raises(Exception):  # Should raise IOError
            validate_vtt_file("/nonexistent/file.vtt")


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
