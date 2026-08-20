from cash_equivalents_mvp.normalization.providers import (
    normalize_code, provider_name_for_code, provider_prefix_for_code, same_provider,
)


def test_provider_name_for_cashable_code():
    assert provider_name_for_code("BNSGICR") == "Bank of Nova Scotia"


def test_provider_name_for_term_deposit_code():
    assert provider_name_for_code("HOBKGICP") == "Home Bank GIC"


def test_provider_name_for_gic_1yr5yr_code():
    assert provider_name_for_code("HOBK") == "Home Bank GIC"


def test_provider_name_handles_leading_whitespace():
    assert provider_name_for_code(" BNSGICP") == "Bank of Nova Scotia"


def test_provider_name_unknown_code_returns_none():
    assert provider_name_for_code("ZZZUNKNOWN") is None


def test_normalize_code_strips_whitespace_and_uppercases():
    assert normalize_code(" bnsgicr ") == "BNSGICR"


def test_same_provider_across_product_suffixes():
    # BNSGICR (cashable), BNSGICP (term deposit), BNSG (1yr-5yr) are all Bank of Nova Scotia.
    assert same_provider("BNSGICR", "BNSGICP")
    assert same_provider("BNSGICR", "BNSG")


def test_same_provider_false_for_different_providers():
    assert not same_provider("BNSGICR", "EQBGICR")


def test_prefix_disambiguates_similar_codes():
    # BMO / BMT / BOM must not collide despite sharing the "B" prefix.
    assert provider_prefix_for_code("BMOGICP") == "BMO"
    assert provider_prefix_for_code("BMTGICP") == "BMT"
    assert provider_prefix_for_code("BOMGICP") == "BOM"
