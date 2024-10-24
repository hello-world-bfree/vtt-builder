# vtt_builder

Simple and fast functions for building VTT formatted transcripts.

## Assumptions

The builder functions makes a few assumptions.

First, it assumes that the data is stored either in JSON files or as a Python dict with the following keys - `transcript` and `segments`.

It also assumes that the transcript is already broken up into segments with the appropriate timestamps in the following schema - a list of these objects is what should be in `segments`:

|key|type|description|
|---|---|---|
|id|integer|Unique, ordered identifier of the segment.|
|start|number|Start time of the segment in seconds.|
|end|number|End time of the segment in seconds.|
|text|string|Text content of the segment.|

`transcript` should store the plain text of the segments together. This allows for combining text from multiple files.

## Functions

### `build_vtt_from_json_files(file_paths: list(str), output_file: str)`

Builds one VTT formatted transcript from one or more JSON files. The function will assume the file paths are provided in order. In this way, the output VTT transcript will build from the files before it, adding the `start` and `end` times as it goes to make the output one, coherent transcript.

#### Arguments:

- `file_paths` (*list[str]*): The JSON file paths that'll make up the transcript.
- `output_file` (*str*): The file path opf the output VTT formatted transcript.

---

### `build_transcript_from_json_files`

From plain text transcripts within multiple JSON files, build a single, plain text transcript with each chunk separated by a newline.

#### Arguments:

- `file_paths` (*list[str]*): The JSON file paths that'll make up the transcript.
- `output_file` (*str*): The file path opf the output VTT formatted transcript.

---

### `build_vtt_from_records`

From a list of segments - a list of Python dictionaries - build the VTT transcript.

#### Arguments:

- `segments_list` (*list[dict]*): A list of transcript segments (see schema above).
- `output_file` (*str*): The file path opf the output VTT formatted transcript.

---

### `validate_vtt_file`

Validate a VTT file.

#### Arguments:

- `vtt_file` (*string*): A complete file path to the vtt file.

#### Returns:

- (*boolean*): A true or false value indicating whether it's a valid VTT formatted file or not.

#### Example

```python
test_fail = validate_vtt_file('/Users/user/not_vtt.json')
print(test_fail) # False

test_pass = validate_vtt_file('/Users/user/legit_vtt.vtt') 
# The extension does not matter
print(test_pass) # True
```

---