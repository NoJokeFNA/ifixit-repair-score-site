import re
from typing import List

from constants import TAG_PRIORITIES, FLAG_TO_TAG, METADATA_KEYS


def _tag_priority(tags: List[str]) -> int:
    """Returns the priority rank for a list of tags.

    Args:
        tags: List of tag strings.

    Returns:
        int: Priority value (0 = starred, 1 = user_contributed, 2 = other).
    """
    return min((TAG_PRIORITIES.get(tag, 2) for tag in tags), default=2)


def _build_tags_from_flags(raw_flags: list[str] | set[str]) -> list[str]:
    """Builds a stable, lowercase tag list from raw flags.

    Args:
        raw_flags: Iterable of raw flag strings.

    Returns:
        List of lowercase tags derived from known flags.
    """
    return [tag for flag, tag in FLAG_TO_TAG.items() if flag in raw_flags]


def _to_ifixit_title(name: str) -> str:
    """
    Converts a human-readable device name into a normalized iFixit wiki title.

    The conversion applies the following rules:
    - Strips leading and trailing whitespace.
    - Replaces all sequences of whitespace (spaces, tabs, etc.) with a single underscore (_).
    - Replaces any character that is not a letter, digit, underscore, parenthesis, dot, or hyphen
      with an underscore.
    - Collapses multiple consecutive underscores into a single underscore.
    - Replaces '(' with '%28' and ')' with '%29' for URL safety.

    Example:
        'Samsung Galaxy S22 Ultra' -> 'Samsung_Galaxy_S22_Ultra'
        'Motorola Edge 5G UW (2021)' -> 'Motorola_Edge_5G_UW_%282021%29'

    Args:
        name: Human-readable device name.

    Returns:
        A normalized iFixit wiki title.
    """
    s = re.sub(r"\s+", "_", name.strip())
    s = re.sub(r"[^A-Za-z0-9_().\-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = re.sub(r"\(", "%28", s)
    s = re.sub(r"\)", "%29", s)

    return s


def _is_metadata_key(key: str) -> bool:
    """Returns whether a key is considered metadata and should be skipped."""
    return key in METADATA_KEYS


def _normalize_key(s: str) -> str:
    """Normalized key for robust matching between categories/devices and guide groups."""
    return _to_ifixit_title(s).lower()
