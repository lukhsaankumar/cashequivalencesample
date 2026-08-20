from cash_equivalents_mvp.orchestration.graph import (
    DEPENDENCIES, build_registry, downstream_of, topological_order,
)


def test_registry_has_an_entry_for_every_dependency_key():
    registry = build_registry()
    assert set(DEPENDENCIES.keys()) == set(registry.keys())


def test_topological_order_respects_dependencies():
    order = topological_order()
    index = {rid: i for i, rid in enumerate(order)}
    for rid, deps in DEPENDENCIES.items():
        for dep in deps:
            assert index[dep] < index[rid], f"{dep} must come before {rid}"


def test_workbook_rendering_depends_on_all_collectors():
    deps = set(DEPENDENCIES["workbook_rendering"])
    for collector in ("gic_rates", "canada_prime", "us_fed_funds", "money_market",
                       "treasury_bills", "hisa", "template", "report_date"):
        assert collector in deps


def test_downstream_of_gic_rates_includes_rendering_pdf_and_package():
    downstream = downstream_of("gic_rates")
    assert "workbook_rendering" in downstream
    assert "pdf_export" in downstream
    assert "package" in downstream


def test_downstream_of_gic_rates_excludes_unrelated_collectors():
    # A manual fix to gic_rates must never trigger a rerun of unrelated successful collectors.
    downstream = downstream_of("gic_rates")
    for unrelated in ("canada_prime", "us_fed_funds", "hisa", "treasury_bills", "money_market"):
        assert unrelated not in downstream


def test_downstream_order_is_dependency_safe():
    downstream = downstream_of("hisa")
    assert downstream.index("workbook_rendering") < downstream.index("pdf_export")
    assert downstream.index("pdf_export") < downstream.index("package")
