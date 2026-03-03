#!/usr/bin/env python3
"""
Translation JSON converter — forward and reverse conversion.

Forward:  multiple lang JSON files → grouped.txt + mapping.json
Reverse:  grouped.txt + mapping.json + language codes → per-lang JSON files
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json_ordered(path: str) -> OrderedDict:
    """Load a JSON file preserving insertion order."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=OrderedDict)


def dump_json(data: OrderedDict, path: str) -> None:
    """Write an OrderedDict as pretty-printed JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_grouped_file(path: str) -> dict:
    """
    Parse a grouped translation file into {id: [translation, ...]} dict.

    Expected format:
        ==1==
        "First language value"
        "Second language value"

        ==2==
        ...
    """
    groups = {}
    current_id = None
    in_multiline_string = False
    multiline_buffer = ""

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            # Section header
            header_match = re.fullmatch(r"==(\d+)==", line.strip())
            if header_match:
                # Save any buffered multiline content before starting new group
                if in_multiline_string and current_id is not None:
                    groups[current_id].append(multiline_buffer)
                    multiline_buffer = ""
                    in_multiline_string = False
                
                current_id = int(header_match.group(1))
                groups[current_id] = []
                continue

            # Skip blank lines between groups
            if line.strip() == "":
                # If we're in a multiline string, a blank line ends it
                if in_multiline_string:
                    groups[current_id].append(multiline_buffer)
                    multiline_buffer = ""
                    in_multiline_string = False
                continue

            # Translation line
            if current_id is None:
                raise ValueError(
                    f"Translation line found before any group header: {line!r}"
                )

            # Check if this is the start of a multiline string
            if line.startswith('"') and not line.endswith('"'):
                in_multiline_string = True
                multiline_buffer = line[1:]  # Remove opening quote, keep the rest
            elif in_multiline_string:
                # We're in a multiline string, add this line to buffer
                if line.endswith('"'):
                    # End of multiline string
                    multiline_buffer += "\n" + line[:-1]  # Add line with newline, remove closing quote
                    # Unescape internal escaped double-quotes only (keep newlines as \\n for JSON parsing)
                    multiline_buffer = multiline_buffer.replace('\\"', '"')
                    groups[current_id].append(multiline_buffer)
                    multiline_buffer = ""
                    in_multiline_string = False
                else:
                    # Continue multiline string
                    multiline_buffer += "\n" + line
            else:
                # Single line translation
                if line.startswith('"') and line.endswith('"'):
                    value = line[1:-1]
                    # Unescape internal escaped double-quotes only (keep newlines as \\n for JSON parsing)
                    value = value.replace('\\"', '"')
                else:
                    value = line
                groups[current_id].append(value)

    # Handle case where file ends while still in multiline string
    if in_multiline_string and current_id is not None:
        # Unescape internal escaped double-quotes only (keep newlines as \\n for JSON parsing)
        multiline_buffer = multiline_buffer.replace('\\"', '"')
        groups[current_id].append(multiline_buffer)

    return groups


# ---------------------------------------------------------------------------
# Forward conversion
# ---------------------------------------------------------------------------

def forward_convert(lang_files, output_grouped, output_mapping):
    """
    Convert multiple language JSON files to a grouped translation file and
    a mapping JSON.

    Parameters
    ----------
    lang_files      : ordered list of JSON file paths; the first defines ordering
    output_grouped  : path for the numbered grouped text output
    output_mapping  : path for the key->id mapping JSON
    """
    if not lang_files:
        raise ValueError("At least one language file must be provided.")

    # Load all language data
    lang_data = []
    for path in lang_files:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Language file not found: {path}")
        lang_data.append(load_json_ordered(path))

    reference = lang_data[0]  # defines ordering

    # Validate that every language contains every section+key from reference
    for idx, (lang_dict, lang_path) in enumerate(zip(lang_data[1:], lang_files[1:]), start=2):
        for section, keys in reference.items():
            if section not in lang_dict:
                print(
                    f"Warning: section '{section}' missing in file #{idx} "
                    f"({lang_path}). Empty strings will be used.",
                    file=sys.stderr,
                )
            else:
                for key in keys:
                    if key not in lang_dict[section]:
                        pass

    # Build mapping and grouped output in reference order
    mapping = OrderedDict()
    grouped_lines = []
    current_id = 0

    for section, keys in reference.items():
        mapping[section] = OrderedDict()
        for key in keys:
            current_id += 1
            mapping[section][key] = current_id

            grouped_lines.append(f"=={current_id}==")
            for lang_dict in lang_data:
                value = lang_dict.get(section, {}).get(key, "")
                # Convert non-string values to JSON string representation
                if not isinstance(value, str):
                    value = json.dumps(value, ensure_ascii=False)
                # Escape any literal newlines and double-quotes inside the value
                escaped = value.replace('\n', '\\n').replace('"', '\\"')
                grouped_lines.append(f'"{escaped}"')
            grouped_lines.append("")  # blank line separator

    # Write outputs
    Path(output_grouped).parent.mkdir(parents=True, exist_ok=True)
    with open(output_grouped, "w", encoding="utf-8") as f:
        f.write("\n".join(grouped_lines).rstrip("\n") + "\n")

    Path(output_mapping).parent.mkdir(parents=True, exist_ok=True)
    dump_json(mapping, output_mapping)

    print(
        f"Forward conversion complete.\n"
        f"  Languages : {len(lang_files)}\n"
        f"  Total keys: {current_id}\n"
        f"  Grouped   -> {output_grouped}\n"
        f"  Mapping   -> {output_mapping}"
    )


# ---------------------------------------------------------------------------
# Reverse conversion
# ---------------------------------------------------------------------------

def reverse_convert(grouped_file, mapping_file, language_codes, output_dir):
    """
    Reconstruct per-language JSON files from a grouped translation file and
    a mapping JSON.

    Parameters
    ----------
    grouped_file    : path to the grouped text file produced by forward_convert
    mapping_file    : path to the mapping JSON produced by forward_convert
    language_codes  : ordered list of language codes (must match forward order)
    output_dir      : directory where reconstructed JSONs will be written
    """
    if not language_codes:
        raise ValueError("At least one language code must be provided.")

    # Load inputs
    for path in (grouped_file, mapping_file):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")

    groups = parse_grouped_file(grouped_file)
    mapping = load_json_ordered(mapping_file)

    n_langs = len(language_codes)

    # Validate group sizes against language count
    for gid, translations in groups.items():
        if len(translations) != n_langs:
            raise ValueError(
                f"Group =={gid}== has {len(translations)} translation(s) but "
                f"{n_langs} language(s) were specified. "
                "Check that --languages matches the original forward conversion."
            )

    # Collect all expected IDs from mapping
    expected_ids = set()
    for section, keys in mapping.items():
        for key, gid in keys.items():
            expected_ids.add(gid)

    missing_ids = expected_ids - set(groups.keys())
    if missing_ids:
        raise ValueError(
            f"The following group IDs are in the mapping but missing from the "
            f"grouped file: {sorted(missing_ids)}"
        )

    # Build one OrderedDict per language
    lang_dicts = [OrderedDict() for _ in language_codes]

    for section, keys in mapping.items():
        for lang_dict in lang_dicts:
            lang_dict[section] = OrderedDict()

        for key, gid in keys.items():
            if gid not in groups:
                raise ValueError(
                    f"Group ID {gid} (section='{section}', key='{key}') not "
                    f"found in grouped file."
                )
            translations = groups[gid]
            for lang_idx, translation in enumerate(translations):
                # Only parse as JSON if it looks like an object or array
                # This prevents converting string literals like "false" to boolean false
                if translation.strip().startswith(('{', '[')):
                    try:
                        parsed_value = json.loads(translation)
                        lang_dicts[lang_idx][section][key] = parsed_value
                    except (json.JSONDecodeError, TypeError):
                        # If parsing fails, keep as string with unescaped newlines
                        lang_dicts[lang_idx][section][key] = translation.replace('\\n', '\n')
                else:
                    # Keep as string, but unescape newlines
                    lang_dicts[lang_idx][section][key] = translation.replace('\\n', '\n')

    # Write per-language JSON files
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for lang_code, lang_dict in zip(language_codes, lang_dicts):
        out_path = os.path.join(output_dir, f"{lang_code}.client.json")
        dump_json(lang_dict, out_path)
        print(f"  Written -> {out_path}")

    print(
        f"Reverse conversion complete.\n"
        f"  Languages restored: {n_langs}\n"
        f"  Output directory  : {output_dir}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="Convert translation JSON files to/from a grouped format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Forward conversion:
    python converter.py forward \\
      --output grouped.txt \\
      --mapping mapping.json \\
      en.client.json fr.client.json sv.client.json id.client.json

  Reverse conversion:
    python converter.py reverse \\
      --grouped grouped.txt \\
      --mapping mapping.json \\
      --languages en fr sv id \\
      --output-dir restored/
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- forward -----------------------------------------------------------
    fwd = sub.add_parser("forward", help="Convert JSON files -> grouped + mapping")
    fwd.add_argument(
        "lang_files",
        metavar="LANG_FILE",
        nargs="+",
        help="Language JSON files. The FIRST file defines key/section ordering.",
    )
    fwd.add_argument(
        "--output", "-o",
        default="grouped.txt",
        metavar="FILE",
        help="Path for the grouped translation output (default: grouped.txt)",
    )
    fwd.add_argument(
        "--mapping", "-m",
        default="mapping.json",
        metavar="FILE",
        help="Path for the mapping JSON output (default: mapping.json)",
    )

    # -- reverse -----------------------------------------------------------
    rev = sub.add_parser("reverse", help="Reconstruct JSON files from grouped + mapping")
    rev.add_argument(
        "--grouped", "-g",
        required=True,
        metavar="FILE",
        help="Path to the grouped translation file",
    )
    rev.add_argument(
        "--mapping", "-m",
        required=True,
        metavar="FILE",
        help="Path to the mapping JSON file",
    )
    rev.add_argument(
        "--languages", "-l",
        required=True,
        nargs="+",
        metavar="LANG",
        help="Ordered language codes matching the original forward conversion order",
    )
    rev.add_argument(
        "--output-dir", "-d",
        default="restored",
        metavar="DIR",
        help="Directory to write reconstructed JSON files (default: restored/)",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "forward":
            forward_convert(
                lang_files=args.lang_files,
                output_grouped=args.output,
                output_mapping=args.mapping,
            )
        elif args.command == "reverse":
            reverse_convert(
                grouped_file=args.grouped,
                mapping_file=args.mapping,
                language_codes=args.languages,
                output_dir=args.output_dir,
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()