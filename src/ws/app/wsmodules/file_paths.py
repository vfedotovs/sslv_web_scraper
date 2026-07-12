#!/usr/bin/env python3
"""file_paths.py — M7 P7: city-scoped intermediate filenames.

Every pipeline stage hands data to the next through files in the
container working directory. Until M7 P7 those names were fixed
(pandas_df.csv, cleaned-sorted-df.csv, ...), so two city runs in one
container would silently overwrite each other mid-pipeline. Each stage
now derives its input/output names through city_file(), keeping the
legacy un-prefixed name when no city is given (standalone runs, old
callers).
"""


def city_file(base_name: str, city: str = None) -> str:
    """Return '{city}-{base_name}' when a city slug is given, else the
    legacy base_name. Single naming rule for every stage hand-off file."""
    return f"{city}-{base_name}" if city else base_name
