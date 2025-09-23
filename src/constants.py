from typing import Final

TAG_PRIORITIES: Final[dict[str, int]] = {
    "starred": 0,
    "user_contributed": 1,
}

FLAG_TO_TAG: Final[dict[str, str]] = {
    "GUIDE_ARCHIVED": "archived",
    "GUIDE_STARRED": "starred",
    "GUIDE_USER_CONTRIBUTED": "user_contributed",
}

METADATA_KEYS: Final[set[str]] = {
    "attrs",
    "contents_json",
    "image",
    "inheritedFrom",
    "parts",
    "repairability_score",
    "source_revisionid",
}
