from typing import Final

TAG_PRIORITIES: Final[dict[str, int]] = {
    "starred": 0,
    "user_contributed": 1,
}

FLAG_TO_TAG: Final[dict[str, str]] = {
    "GUIDE_ARCHIVED": "archived",
    "GUIDE_STARRED": "starred",
    "GUIDE_USER_CONTRIBUTED": "user_contributed",
    # I will think of a better way to do this in the future.
    # "GUIDE_IN_PROGRESS": "in_progress",
    # "GUIDE_MISSING_IMAGES": "missing_images",
    # "GUIDE_MISSING_STEPS": "missing_steps",
    # "INTRODUCTION_ISSUES": "introduction_issues",
    # "NO_DETAILS": "no_details"
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
