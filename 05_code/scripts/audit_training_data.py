"""Aggregate-only audit of possible ML supervision. Never exports user rows or IDs."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from alfa_reco.cli import atomic_json, load_bundle


def audit(conn):
    def scalar(query):
        return conn.execute(query).fetchone()[0]

    return {
        "course_bindings": scalar('SELECT count(*) FROM "CourseUserBindings"'),
        "users_with_course": scalar('SELECT count(DISTINCT "UserId") FROM "CourseUserBindings"'),
        "distinct_courses": scalar('SELECT count(DISTINCT "CourseId") FROM "CourseUserBindings"'),
        "single_course_users": scalar("""SELECT count(*) FROM (
            SELECT "UserId" FROM "CourseUserBindings" GROUP BY "UserId"
            HAVING count(DISTINCT "CourseId") = 1)"""),
        "completed_bindings": scalar("""SELECT count(*) FROM "CourseUserBindings"
            WHERE "IsCompleted" = 't' """),
        "paid_flag_true": scalar(
            """SELECT count(*) FROM "CourseUserBindings" WHERE "IsPaid" = 't' """
        ),
        "nonempty_buying_date": scalar("""SELECT count(*) FROM "CourseUserBindings"
            WHERE "BuyingDate" IS NOT NULL AND trim("BuyingDate") <> '' """),
        "course_completion_before_created": scalar("""SELECT count(*) FROM "CourseUserBindings"
            WHERE "Completed" < "Created" """),
        "lesson_bindings": scalar('SELECT count(*) FROM "CourseUserLessonBindings"'),
        "lesson_completion_before_created": scalar("""SELECT count(*) FROM "CourseUserLessonBindings"
            WHERE "Completed" < "Created" """),
        "ratings": scalar('SELECT count(*) FROM "UserRatings"'),
        "ratings_with_user": scalar(
            """SELECT count(*) FROM "UserRatings" WHERE "UserId" IS NOT NULL"""
        ),
        "rating_distribution": {
            str(value): count
            for value, count in conn.execute(
                'SELECT "Value", count(*) FROM "UserRatings" GROUP BY "Value" ORDER BY "Value"'
            )
        },
        "limitations": [
            "Counts describe raw rows, not verified exposure, intent, entitlement or purchases.",
            "Current completion is not a timestamped past feature; dates require semantic verification.",
            "Unobserved user-item pairs are unlabeled, not negatives.",
            "The supplied schema has no verified search-query/impression log.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="artifacts/catalog")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path, manifest, _ = load_bundle(args.catalog)
    with closing(
        sqlite3.connect((path / "source.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
        report = audit(conn)
    report["catalog_sha256"] = manifest["catalog_sha256"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, report)
    print(args.output)


if __name__ == "__main__":
    main()
