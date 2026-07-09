#!/usr/bin/env python3
"""
Optional runtime loader for config/cities.yaml (Phase 4 Item 12).

Provides city metadata (display_name, main_url, email_title) for validation,
logging, and fallbacks when env vars like EMAIL_CITY_TITLE are not set.

Usage is optional; the app primarily relies on CITY_MAIN_URL and EMAIL_CITY_TITLE
per-container env vars for multi-city isolation.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.getenv(
    "CITIES_CONFIG_PATH",
    str(Path(__file__).parent.parent.parent.parent.parent / "config" / "cities.yaml")
)


def load_cities(config_path: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """
    Load cities from YAML file.

    Returns dict like:
    {
        "jurmala": {
            "display_name": "Jūrmala",
            "main_url": "https://...",
            "email_title": "Jūrmala Apartments for sale"
        },
        ...
    }

    If file not found or yaml not installed, returns {} (graceful).
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    if yaml is None:
        logger.warning("PyYAML not installed; skipping cities.yaml load. "
                       "Install pyyaml or set CITIES_CONFIG_PATH to enable runtime city config.")
        return {}

    path = Path(config_path)
    if not path.exists():
        logger.debug(f"cities.yaml not found at {config_path} (optional for runtime)")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cities = data.get("cities", {})
        if not isinstance(cities, dict):
            logger.warning("Invalid cities.yaml structure; expected 'cities:' dict")
            return {}

        # Basic validation
        validated = {}
        for slug, info in cities.items():
            if not isinstance(info, dict):
                logger.warning(f"Invalid entry for city '{slug}'")
                continue
            required = ["display_name", "main_url", "email_title"]
            if all(k in info for k in required):
                validated[slug] = {
                    "display_name": str(info["display_name"]),
                    "main_url": str(info["main_url"]),
                    "email_title": str(info["email_title"]),
                }
            else:
                logger.warning(f"City '{slug}' missing required keys: {required}")

        logger.info(f"Loaded {len(validated)} cities from {config_path}")
        return validated
    except Exception as e:
        logger.warning(f"Failed to load cities.yaml: {e}")
        return {}


_cities_cache: Optional[Dict[str, Dict[str, str]]] = None


def get_cities() -> Dict[str, Dict[str, str]]:
    """Cached loader."""
    global _cities_cache
    if _cities_cache is None:
        _cities_cache = load_cities()
    return _cities_cache


def get_city_info(slug: str) -> Optional[Dict[str, str]]:
    """Get info for a specific city slug (e.g. 'jurmala')."""
    return get_cities().get(slug)


def get_display_name(slug: str, default: Optional[str] = None) -> Optional[str]:
    """Convenience: get display name or fallback."""
    info = get_city_info(slug)
    if info:
        return info["display_name"]
    return default


def validate_city_slug(slug: str) -> bool:
    """Check if slug is known (if config loaded)."""
    cities = get_cities()
    if not cities:
        return True  # no config, assume valid
    return slug in cities


if __name__ == "__main__":
    cities = load_cities()
    print(f"Known cities: {list(cities.keys())}")
    print(get_city_info("jurmala"))
