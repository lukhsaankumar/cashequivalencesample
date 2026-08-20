"""Static responsibility dependency graph (master prompt §10).

    template, report_date
    gic_rates, canada_prime, us_fed_funds, money_market, treasury_bills, hisa   (independent)
              |
        workbook_rendering   (populate + recalculate EN & FR)
              |
          pdf_export
              |
           package
"""
from __future__ import annotations

from cash_equivalents_mvp.responsibilities.base import Responsibility
from cash_equivalents_mvp.responsibilities.canada_prime import CanadaPrimeResponsibility
from cash_equivalents_mvp.responsibilities.fed_funds import FedFundsResponsibility
from cash_equivalents_mvp.responsibilities.gic_rates import GicRatesResponsibility
from cash_equivalents_mvp.responsibilities.hisa import HisaResponsibility
from cash_equivalents_mvp.responsibilities.money_market import MoneyMarketResponsibility
from cash_equivalents_mvp.responsibilities.package import PackageResponsibility
from cash_equivalents_mvp.responsibilities.pdf_export import PdfExportResponsibility
from cash_equivalents_mvp.responsibilities.report_date import ReportDateResponsibility
from cash_equivalents_mvp.responsibilities.templates import TemplateResponsibility
from cash_equivalents_mvp.responsibilities.treasury_bills import TreasuryBillsResponsibility
from cash_equivalents_mvp.responsibilities.workbook_rendering import WorkbookRenderingResponsibility

COLLECTOR_IDS = (
    "gic_rates", "canada_prime", "us_fed_funds", "money_market", "treasury_bills", "hisa",
)

WORKBOOK_RENDERING_DEPS = ("template", "report_date", *COLLECTOR_IDS)


def build_registry() -> dict[str, Responsibility]:
    """Fresh instances every call — responsibilities are stateless, all state lives in the DB."""
    return {
        "template": TemplateResponsibility(),
        "report_date": ReportDateResponsibility(),
        "gic_rates": GicRatesResponsibility(),
        "canada_prime": CanadaPrimeResponsibility(),
        "us_fed_funds": FedFundsResponsibility(),
        "money_market": MoneyMarketResponsibility(),
        "treasury_bills": TreasuryBillsResponsibility(),
        "hisa": HisaResponsibility(),
        "workbook_rendering": WorkbookRenderingResponsibility(),
        "pdf_export": PdfExportResponsibility(),
        "package": PackageResponsibility(),
    }


DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "template": (),
    "report_date": (),
    "gic_rates": (),
    "canada_prime": (),
    "us_fed_funds": (),
    "money_market": (),
    "treasury_bills": (),
    "hisa": (),
    "workbook_rendering": WORKBOOK_RENDERING_DEPS,
    "pdf_export": ("workbook_rendering",),
    "package": ("pdf_export",),
}


def downstream_of(responsibility_id: str) -> list[str]:
    """Every responsibility that (transitively) depends on responsibility_id, in dependency order."""
    result: list[str] = []
    changed = True
    frontier = {responsibility_id}
    while changed:
        changed = False
        for rid, deps in DEPENDENCIES.items():
            if rid in result:
                continue
            if frontier & set(deps):
                result.append(rid)
                frontier.add(rid)
                changed = True
    # stable dependency order
    order = topological_order()
    return [rid for rid in order if rid in result]


def topological_order() -> list[str]:
    visited: set[str] = set()
    order: list[str] = []

    def visit(rid: str) -> None:
        if rid in visited:
            return
        visited.add(rid)
        for dep in DEPENDENCIES.get(rid, ()):
            visit(dep)
        order.append(rid)

    for rid in DEPENDENCIES:
        visit(rid)
    return order
