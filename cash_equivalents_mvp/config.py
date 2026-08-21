"""Loads config/*.yaml. No secrets live here — see SECURITY.md for credential handling."""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@functools.lru_cache(maxsize=1)
def settings() -> dict:
    return _load_yaml("settings.yaml")


@functools.lru_cache(maxsize=1)
def sources_config() -> dict:
    return _load_yaml("sources.yaml")["sources"]


@functools.lru_cache(maxsize=None)  # keyed by language ("en"/"fr") — maxsize=1 would thrash
def workbook_map(language: str) -> dict:
    if language not in ("en", "fr"):
        raise ValueError(f"Unsupported language {language!r}; expected 'en' or 'fr'")
    return _load_yaml(f"workbook_map_{language}.yaml")


def resolve_sheet_name(language: str, section_key: str) -> str:
    """workbook_map_*.yaml sections store `sheet:` as an alias key (e.g. 'hisa') into the
    top-level `sheets:` dict, not a literal Excel sheet name — resolve it here so every
    responsibility does this the same way instead of each re-implementing the lookup."""
    wmap = workbook_map(language)
    alias = wmap[section_key]["sheet"]
    return wmap["sheets"][alias]


@functools.lru_cache(maxsize=1)
def business_rules() -> dict:
    return _load_yaml("business_rules.yaml")


@functools.lru_cache(maxsize=1)
def provider_aliases() -> dict:
    return _load_yaml("provider_aliases.yaml")["providers"]


def source_material_dir() -> Path:
    return REPO_ROOT / settings()["source_material_dir"]


def output_root_dir() -> Path:
    d = REPO_ROOT / settings()["output_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_dir() -> Path:
    d = REPO_ROOT / settings()["upload_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def raw_sources_dir() -> Path:
    d = REPO_ROOT / settings()["raw_sources_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def browser_profile_dir() -> Path:
    """Root for named persistent Playwright browser profiles — session cookies only, never
    passwords. Under local_data/, already fully gitignored. See SECURITY.md."""
    d = REPO_ROOT / settings()["browser_profile_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def database_path() -> Path:
    p = REPO_ROOT / settings()["database_path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log_dir() -> Path:
    d = REPO_ROOT / settings()["log_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear_caches() -> None:
    """Used by tests that swap in temp config directories."""
    settings.cache_clear()
    sources_config.cache_clear()
    workbook_map.cache_clear()
    business_rules.cache_clear()
    provider_aliases.cache_clear()
