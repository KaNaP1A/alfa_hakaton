import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.import_review_csv import import_review


class ReviewCsvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        pool = [
            {
                "query_id": "q",
                "candidates": [{"entity_key": "article:1"}, {"entity_key": "course:2"}],
            }
        ]
        data = "\n".join(json.dumps(row) for row in pool) + "\n"
        (self.root / "pool.jsonl").write_text(data)
        digest = hashlib.sha256(data.encode()).hexdigest()
        (self.root / "manifest.json").write_text(
            json.dumps({"hashes_before_review": {"pool.jsonl": digest}})
        )

    def csv(self, rows):
        path = self.root / "review.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["query_id", "entity_key", "grade"])
            writer.writerows(rows)
        return path

    def test_blank_stays_unknown_and_only_own_column_is_filled(self):
        source = self.csv([("q", "article:1", "3"), ("q", "course:2", "")])
        out = self.root / "a.jsonl"
        self.assertEqual(import_review(self.root, source, out, "reviewer_a"), (2, 1))
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        self.assertEqual(rows[0]["reviewer_a"], 3)
        self.assertIsNone(rows[0]["reviewer_b"])
        self.assertIsNone(rows[1]["reviewer_a"])

    def test_duplicate_missing_and_invalid_grade_are_rejected(self):
        for rows in (
            [("q", "article:1", "1"), ("q", "article:1", "2")],
            [("q", "article:1", "2")],
            [("q", "article:1", "5"), ("q", "course:2", "")],
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    import_review(self.root, self.csv(rows), self.root / "out", "reviewer_b")

    def test_frozen_pool_tampering_is_rejected(self):
        source = self.csv([("q", "article:1", "3"), ("q", "course:2", "0")])
        (self.root / "pool.jsonl").write_text("changed")
        with self.assertRaisesRegex(ValueError, "Pool changed"):
            import_review(self.root, source, self.root / "out", "reviewer_a")

    def test_excel_semicolon_csv_with_separator_hint(self):
        source = self.root / "excel.csv"
        source.write_text(
            "sep=;\nquery_id;entity_key;grade\nq;article:1;3\nq;course:2;\n", encoding="utf-8-sig"
        )
        out = self.root / "out.jsonl"
        self.assertEqual(import_review(self.root, source, out, "reviewer_a"), (2, 1))
        self.assertIsNone(json.loads(out.read_text().splitlines()[1])["reviewer_a"])

    def test_excel_xlsx_reads_grades_and_blank(self):
        source = self.root / "review.xlsx"
        workbook = '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Разметка" sheetId="1" r:id="rId1"/></sheets></workbook>'
        rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
        sheet = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
        <row r="1"><c r="A1" t="inlineStr"><is><t>grade</t></is></c><c r="B1" t="inlineStr"><is><t>query_id</t></is></c><c r="C1" t="inlineStr"><is><t>entity_key</t></is></c></row>
        <row r="2"><c r="A2"><v>0</v></c><c r="B2" t="s"><v>0</v></c><c r="C2" t="inlineStr"><is><t>article:1</t></is></c></row>
        <row r="3"><c r="B3" t="s"><v>0</v></c><c r="C3" t="inlineStr"><is><t>course:2</t></is></c></row>
        </sheetData></worksheet>"""
        shared = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>q</t></si></sst>'
        with ZipFile(source, "w") as archive:
            for path, data in (
                ("xl/workbook.xml", workbook),
                ("xl/_rels/workbook.xml.rels", rels),
                ("xl/worksheets/sheet1.xml", sheet),
                ("xl/sharedStrings.xml", shared),
            ):
                archive.writestr(path, data)
        out = self.root / "xlsx.jsonl"
        self.assertEqual(import_review(self.root, source, out, "reviewer_a"), (2, 1))
        ratings = [json.loads(row)["reviewer_a"] for row in out.read_text().splitlines()]
        self.assertEqual(ratings, [0, None])
