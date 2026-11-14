"""Import one independent review without treating blank ratings as negatives."""

import argparse
import csv
import hashlib
import json
import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


def xlsx_rows(source):
    """Read the supplied review sheet, including Excel inline/shared strings, without extra packages."""
    ns = {
        "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "p": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(
            (s for s in workbook.findall("x:sheets/x:sheet", ns) if s.get("name") == "Разметка"),
            None,
        )
        if sheet is None:
            raise ValueError("Missing worksheet Разметка")
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_id = sheet.get("{" + ns["r"] + "}id")
        relationship = next(
            (r for r in rels.findall("p:Relationship", ns) if r.get("Id") == rel_id), None
        )
        if relationship is None or relationship.get("TargetMode") == "External":
            raise ValueError("Invalid worksheet relationship")
        target = relationship.get("Target", "")
        path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
        if not path.startswith("xl/worksheets/"):
            raise ValueError("Invalid worksheet path")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = [
                "".join(t.text or "" for t in si.iter("{" + ns["x"] + "}t"))
                for si in shared.findall("x:si", ns)
            ]
        root = ET.fromstring(archive.read(path))
        matrix = []
        for row in root.findall("x:sheetData/x:row", ns):
            cells = {}
            for cell in row.findall("x:c", ns):
                address = re.fullmatch(r"([A-Z]+)[0-9]+", cell.get("r", ""))
                if not address:
                    raise ValueError("Invalid spreadsheet cell reference")
                col = 0
                for letter in address.group(1):
                    col = col * 26 + ord(letter) - ord("A") + 1
                if cell.find("x:f", ns) is not None:
                    raise ValueError("Formulas are not accepted in review files")
                kind = cell.get("t")
                if kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter("{" + ns["x"] + "}t"))
                else:
                    value = cell.findtext("x:v", default="", namespaces=ns)
                    if kind == "s":
                        value = strings[int(value)]
                cells[col - 1] = value
            if cells:
                matrix.append([cells.get(i, "") for i in range(max(cells) + 1)])
    if not matrix:
        raise ValueError("Empty spreadsheet")
    headers = matrix[0]
    if len(set(headers)) != len(headers):
        raise ValueError("Duplicate spreadsheet headers")
    return [
        dict(zip(headers, row + [""] * max(0, len(headers) - len(row)), strict=False))
        for row in matrix[1:]
    ]


def import_review(directory, source, output, reviewer):
    if reviewer not in {"reviewer_a", "reviewer_b"}:
        raise ValueError("Unknown reviewer")
    if output.exists():
        raise ValueError("Output already exists")
    path = directory / "pool.jsonl"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (
        hashlib.sha256(path.read_bytes()).hexdigest()
        != manifest["hashes_before_review"]["pool.jsonl"]
    ):
        raise ValueError("Pool changed since freeze")
    pool = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    expected = {(row["query_id"], item["entity_key"]) for row in pool for item in row["candidates"]}
    rows, seen = [], set()
    if source.suffix.lower() == ".xlsx":
        entries = xlsx_rows(source)
    else:
        with source.open(encoding="utf-8-sig", newline="") as stream:
            first = stream.readline().strip()
            if first.lower() in {"sep=;", "sep=,"}:
                delimiter = first[-1]
            else:
                delimiter = ";" if ";" in first and "," not in first else ","
                stream.seek(0)
            entries = list(csv.DictReader(stream, delimiter=delimiter))
    if not entries or not {"query_id", "entity_key", "grade"} <= set(entries[0]):
        raise ValueError("Expected query_id, entity_key and grade columns")
    for row in entries:
        key = (row["query_id"], row["entity_key"])
        if key in seen or key not in expected:
            raise ValueError("Duplicate or unknown query/candidate pair")
        seen.add(key)
        grade = row["grade"].strip()
        if grade not in {"", "0", "1", "2", "3"}:
            raise ValueError("Grade must be blank or an integer 0–3")
        record = {
            "query_id": key[0],
            "entity_key": key[1],
            "reviewer_a": None,
            "reviewer_b": None,
            "adjudicated": None,
        }
        record[reviewer] = int(grade) if grade else None
        rows.append(record)
    if seen != expected:
        raise ValueError("CSV must contain every original candidate row")
    with output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows), sum(row[reviewer] is not None for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--reviewer", choices=["reviewer_a", "reviewer_b"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows, graded = import_review(args.directory, args.source, args.output, args.reviewer)
    print(f"Imported {graded}/{rows} ratings; blanks remain unknown.")


if __name__ == "__main__":
    main()
