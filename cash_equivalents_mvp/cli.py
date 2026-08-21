"""CLI entry point: python -m cash_equivalents_mvp.cli <command> [options]"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from cash_equivalents_mvp.config import (
    database_path,
    output_root_dir,
    source_material_dir,
    sources_config,
    settings,
    upload_dir,
)
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ManualInput
from cash_equivalents_mvp.orchestration.graph import topological_order
from cash_equivalents_mvp.orchestration.manager import RunManager
from cash_equivalents_mvp.reporting.renderer_selection import select_renderer


def cmd_doctor(_args) -> int:
    print("=== doctor ===")
    ok = True

    print(f"Python: {sys.version.split()[0]}", "OK" if sys.version_info >= (3, 11) else "TOO OLD")
    if sys.version_info < (3, 11):
        ok = False

    for pkg in ("openpyxl", "docx", "fitz", "pydantic", "httpx", "bs4", "yaml", "streamlit"):
        try:
            __import__(pkg)
            print(f"package {pkg}: OK")
        except ImportError as exc:
            print(f"package {pkg}: MISSING ({exc})")
            ok = False

    smd = source_material_dir()
    print(f"source_material dir: {smd}", "OK" if smd.exists() else "MISSING")
    for name in settings()["templates"].values():
        p = smd / name
        print(f"  template {name}:", "OK" if p.exists() else "MISSING")
        if not p.exists():
            ok = False

    for d in (output_root_dir(), upload_dir(), database_path().parent):
        try:
            d.mkdir(parents=True, exist_ok=True)
            testfile = d / ".doctor_write_test"
            testfile.write_text("ok")
            testfile.unlink()
            print(f"writable: {d}: OK")
        except Exception as exc:
            print(f"writable: {d}: FAILED ({exc})")
            ok = False

    renderer_name, _renderer = select_renderer(settings()["renderer"]["preference"])
    if renderer_name:
        print(f"renderer: {renderer_name}: OK")
    else:
        print("renderer: NONE FOUND (Excel COM and LibreOffice both unavailable)")
        ok = False

    try:
        import playwright  # noqa: F401
        print("playwright: OK (optional)")
    except ImportError:
        print("playwright: not installed (optional; only needed for browser-rendered sources)")

    print()
    print("RESULT:", "READY" if ok else "ISSUES FOUND")
    return 0 if ok else 1


def cmd_inspect(args) -> int:
    smd = Path(args.source_dir) if args.source_dir else source_material_dir()
    from cash_equivalents_mvp.audit import sha256_file
    print(f"Inspecting {smd}")
    for f in sorted(smd.glob("*")):
        if f.is_file():
            print(f"  {sha256_file(f)}  {f.name}  ({f.stat().st_size} bytes)")
    return 0


def cmd_bootstrap_mappings(_args) -> int:
    print("Verified mappings already live in config/workbook_map_en.yaml and "
          "config/workbook_map_fr.yaml — see docs/workbook_mapping.md for how each range was "
          "confirmed against the real source files.")
    return 0


def cmd_create_run(args) -> int:
    db = Database(database_path())
    mgr = RunManager(db)
    report_date = date.fromisoformat(args.report_date)
    run = mgr.create_run(report_date)
    print(f"Created run {run.run_id} for {report_date}")
    db.close()
    return 0


def cmd_execute(args) -> int:
    db = Database(database_path())
    mgr = RunManager(db)
    status = mgr.execute_run(args.run_id)
    print(f"Run {args.run_id} finished with status: {status}")
    _print_states(db, args.run_id)
    db.close()
    return 0 if status.value not in ("FAILED",) else 1


def cmd_retry_failed(args) -> int:
    db = Database(database_path())
    mgr = RunManager(db)
    status = mgr.retry_failed(args.run_id)
    print(f"Run {args.run_id} after retry: {status}")
    _print_states(db, args.run_id)
    db.close()
    return 0


def cmd_validate(args) -> int:
    db = Database(database_path())
    findings = db.get_findings(args.run_id)
    blocking = [f for f in findings if f.severity == "blocking"]
    for f in findings:
        print(f"[{f.severity.upper()}] {f.responsibility_id} · {f.rule_id} · {f.message}")
    print(f"\n{len(blocking)} blocking, {len(findings) - len(blocking)} non-blocking")
    db.close()
    return 1 if blocking else 0


def cmd_diagnose(args) -> int:
    db = Database(database_path())
    run = db.get_run_or_raise(args.run_id)
    print(f"Run {args.run_id}: report_date={run.report_date} status={run.status}")
    _print_states(db, args.run_id)
    print("\n--- errors ---")
    for e in db.get_errors(args.run_id):
        print(f"{e.responsibility_id} · {e.stage} · {e.error_code}: {e.message}")
        print(f"  suggested action: {e.suggested_action}")
    db.close()
    return 0


def cmd_demo(_args) -> int:
    """Runs the full pipeline against the historical May 11, 2026 fixture, applying a manual
    override for money_market (the one responsibility whose source requires the IG VPN)."""
    db = Database(database_path())
    mgr = RunManager(db)
    run = mgr.create_run(date(2026, 5, 11))
    print(f"Created demo run {run.run_id}")

    status = mgr.execute_run(run.run_id)
    print(f"After automatic pass: {status}")
    _print_states(db, run.run_id)

    states = db.all_responsibility_states(run.run_id)
    if states.get("money_market", {}).get("status") == "MANUAL_REQUIRED":
        print("\nSupplying manual money_market override (source requires IG VPN)...")
        mi = ManualInput(
            responsibility_id="money_market", kind="numeric",
            numeric_fields={"cad_yield": "2.00", "us_yield": "2.82"},
            override_reason="VPN unavailable in this environment; using historical fixture value for demo",
        )
        manual_status = mgr.submit_manual_input(run.run_id, mi)
        print(f"After manual input: {manual_status}")
        _print_states(db, run.run_id)

    run = db.get_run_or_raise(run.run_id)
    print(f"\nFINAL STATUS: {run.status}")
    if run.output_dir:
        outputs = Path(run.output_dir) / "outputs"
        if outputs.exists():
            print(f"\nOutputs in {outputs}:")
            for f in sorted(outputs.iterdir()):
                print(f"  {f.name}")
    db.close()
    return 0


def _resolve_browser_profile_and_url(args) -> tuple[str, str]:
    """--source <responsibility_id> resolves profile+URL from config/sources.yaml; --profile/--url
    override or supply them directly for sources with no configured browser_profile yet."""
    profile, url = args.profile, args.url
    if args.source:
        cfg = sources_config().get(args.source, {})
        auto_cfg = cfg.get("automatic", {})
        profile = profile or auto_cfg.get("browser_profile")
        url = url or auto_cfg.get("product_page_url") or auto_cfg.get("url") or auto_cfg.get("url_cad") \
            or cfg.get("reference_url")
        if not profile:
            print(f"{args.source!r} has no automatic.browser_profile configured in "
                  f"config/sources.yaml — pass --profile explicitly.")
            sys.exit(2)
    if not profile or not url:
        print("Need either --source <responsibility_id> or both --profile and --url.")
        sys.exit(2)
    return profile, url


def cmd_browser_login(args) -> int:
    from cash_equivalents_mvp.collectors import browser_session
    profile, url = _resolve_browser_profile_and_url(args)
    ok = browser_session.interactive_login(profile, url, timeout_seconds=args.timeout)
    return 0 if ok else 1


def cmd_browser_logout(args) -> int:
    from cash_equivalents_mvp.collectors import browser_session
    if browser_session.logout(args.profile):
        print(f"Session cleared for profile {args.profile!r}.")
    else:
        print(f"No saved session found for profile {args.profile!r}.")
    return 0


def cmd_browser_status(_args) -> int:
    from cash_equivalents_mvp.collectors import browser_session
    profiles: dict[str, list[str]] = {}
    for rid, cfg in sources_config().items():
        p = cfg.get("automatic", {}).get("browser_profile")
        if p:
            profiles.setdefault(p, []).append(rid)
    if not profiles:
        print("No source in config/sources.yaml has automatic.browser_profile configured.")
        return 0
    for profile, sources in profiles.items():
        state = "LOGGED IN (session saved)" if browser_session.has_profile(profile) else "not signed in"
        print(f"{profile:20s} {state:28s} used by: {', '.join(sources)}")
    return 0


def _print_states(db: Database, run_id: str) -> None:
    states = db.all_responsibility_states(run_id)
    for rid in topological_order():
        s = states.get(rid)
        if s:
            print(f"  {rid:22s} {s['status']}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="cash_equivalents_mvp.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)

    p = sub.add_parser("inspect")
    p.add_argument("--source-dir", default=None)
    p.set_defaults(func=cmd_inspect)

    sub.add_parser("bootstrap-mappings").set_defaults(func=cmd_bootstrap_mappings)

    p = sub.add_parser("create-run")
    p.add_argument("--report-date", required=True)
    p.set_defaults(func=cmd_create_run)

    p = sub.add_parser("execute")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_execute)

    p = sub.add_parser("retry-failed")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_retry_failed)

    p = sub.add_parser("validate")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("diagnose")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_diagnose)

    sub.add_parser("demo").set_defaults(func=cmd_demo)

    p = sub.add_parser("browser-login", help="One-time interactive sign-in for an SSO-gated "
                        "source, saved as a persistent local session (see SECURITY.md).")
    p.add_argument("--source", default=None, help="Responsibility id, e.g. gic_rates — resolves "
                    "profile+URL from config/sources.yaml")
    p.add_argument("--profile", default=None, help="Override/explicit profile name")
    p.add_argument("--url", default=None, help="Override/explicit URL to open")
    p.add_argument("--timeout", type=int, default=300, help="Seconds to wait for sign-in")
    p.set_defaults(func=cmd_browser_login)

    p = sub.add_parser("browser-logout", help="Delete a saved browser session (sign out).")
    p.add_argument("--profile", required=True)
    p.set_defaults(func=cmd_browser_logout)

    sub.add_parser("browser-status", help="List configured browser profiles and whether each is "
                    "currently signed in.").set_defaults(func=cmd_browser_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
