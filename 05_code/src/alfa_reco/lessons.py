"""Attach eligible lesson metadata to courses; never expose lesson bodies.

ParentGroupId refers to Lessons.Id within the same course. Unknown flags,
missing parents, cycles and unavailable ancestors fail closed.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime


def parse_as_of(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("as-of must include a timezone")
    return parsed.astimezone(UTC)


def attach_lessons(catalog, lessons, bindings, clean, as_of=None):
    lesson_by_id = {row["Id"]: row for row in lessons}
    courses = {row["source_id"]: row for row in catalog if row["kind"] == "course"}
    by_course = defaultdict(dict)
    duplicate_keys = set()
    for binding in bindings:
        key = (binding["CourseId"], binding["LessonId"])
        if binding["LessonId"] in by_course[binding["CourseId"]]:
            duplicate_keys.add(key)
        by_course[binding["CourseId"]][binding["LessonId"]] = binding
    counts = Counter()

    def blocked(course_id, lesson_id):
        trail = set()
        while True:
            if lesson_id in trail:
                return "ancestor_cycle"
            binding = by_course[course_id].get(lesson_id)
            lesson = lesson_by_id.get(lesson_id)
            if not binding or not lesson:
                return "missing_reference"
            if (course_id, lesson_id) in duplicate_keys:
                return "duplicate_binding"
            if lesson.get("IsDeleted") != "f" or binding.get("IsDeleted") != "f":
                return "deleted_or_unknown"
            if binding.get("IsClosed") != "f":
                return "closed_or_unknown"
            if binding.get("ClosedUntil"):
                try:
                    until = parse_as_of(binding["ClosedUntil"])
                except ValueError:
                    return "invalid_closed_until"
                if as_of is None or until > as_of:
                    return "scheduled"
            parent = binding.get("ParentGroupId")
            if parent:
                if lesson_by_id.get(parent, {}).get("IsGroup") != "t":
                    return "invalid_parent_group"
                trail.add(lesson_id)
                lesson_id = parent
                continue
            return None

    for binding in sorted(bindings, key=lambda row: row["Id"]):
        course = courses.get(binding["CourseId"])
        lesson = lesson_by_id.get(binding["LessonId"])
        if not course:
            counts["course_ineligible"] += 1
            continue
        reason = blocked(binding["CourseId"], binding["LessonId"])
        if reason:
            counts[reason] += 1
            continue
        if lesson.get("IsGroup") != "f":
            counts["group_or_unknown"] += 1
            continue
        # Experts: non-trial lesson contents require verified course access (1 or 2).
        # The anonymous prototype cannot verify that access, even for an open course.
        trial = binding.get("IsTrial") == "t"
        if not trial:
            counts["access_unverified"] += 1
            continue
        title = clean(binding.get("Title")) or clean(lesson.get("Title"))
        if not title:
            counts["empty_title"] += 1
            continue
        course.setdefault("lessons", []).append(
            {
                "lesson_id": lesson["Id"],
                "binding_id": binding["Id"],
                "title": title,
                "description": clean(lesson.get("Description")),
                "is_trial": trial,
                "parent_group_id": binding.get("ParentGroupId"),
                "access_basis": "trial_binding",
                "direct_access_verified": False,
            }
        )
        counts["included_bindings"] += 1
    for course in courses.values():
        course.setdefault("lessons", []).sort(key=lambda row: row["binding_id"])
        course["search_text"] += " " + " ".join(
            lesson["title"] + " " + lesson["description"] for lesson in course["lessons"]
        )
        course["search_text"] = course["search_text"].strip()
    return dict(sorted(counts.items()))
