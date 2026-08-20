"""Reads local_data/test_results/junit.xml and writes test_summary.json grouped by
responsibility / test type / stage / error code / source file, per master prompt §18.
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

JUNIT = Path("local_data/test_results/junit.xml")
OUT = Path("local_data/test_results/test_summary.json")


def responsibility_from_classname(classname: str) -> str:
    known = ["gic_rates", "canada_prime", "us_fed_funds", "money_market", "treasury_bills",
             "hisa", "template", "report_date", "workbook_rendering", "pdf_export", "package"]
    lower = classname.lower()
    for k in known:
        if k in lower:
            return k
    return "n/a"


def test_type_from_path(classname: str) -> str:
    for t in ("unit", "contract", "integration", "fault_injection", "regression"):
        if f".{t}." in classname or classname.startswith(t):
            return t
    return "unknown"


def main():
    tree = ET.parse(JUNIT)
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")

    total = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    passed = total - failures - errors - skipped

    by_type: dict[str, dict[str, int]] = {}
    failing_tests = []

    for case in suite.iter("testcase"):
        classname = case.get("classname", "")
        ttype = test_type_from_path(classname)
        by_type.setdefault(ttype, {"passed": 0, "failed": 0, "skipped": 0})
        failure = case.find("failure")
        error = case.find("error")
        skip = case.find("skipped")
        if failure is not None or error is not None:
            by_type[ttype]["failed"] += 1
            failing_tests.append({
                "responsibility": responsibility_from_classname(classname),
                "test_type": ttype,
                "classname": classname,
                "name": case.get("name"),
                "message": (failure.get("message") if failure is not None else error.get("message")),
            })
        elif skip is not None:
            by_type[ttype]["skipped"] += 1
        else:
            by_type[ttype]["passed"] += 1

    summary = {
        "total_tests": total,
        "passed": passed,
        "failed": failures + errors,
        "skipped": skipped,
        "by_test_type": by_type,
        "failing_tests_grouped": failing_tests,
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
