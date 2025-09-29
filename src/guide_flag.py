from enum import Enum
from typing import Final


class GuideFlag(Enum):
    ARCHIVED = "GUIDE_ARCHIVED"
    STARRED = "GUIDE_STARRED"
    USER_CONTRIBUTED = "GUIDE_USER_CONTRIBUTED"
    IN_PROGRESS = "GUIDE_IN_PROGRESS"
    MISSING_IMAGES = "GUIDE_MISSING_IMAGES"
    MISSING_STEPS = "GUIDE_MISSING_STEPS"
    INTRODUCTION_ISSUES = "INTRODUCTION_ISSUES"
    NO_DETAILS = "NO_DETAILS"

    @property
    def tag(self) -> str:
        return self.name.lower()


FLAG_TO_TAG: Final[dict[str, str]] = {
    flag.value: flag.tag for flag in GuideFlag
}

TAG_PRIORITIES: Final[dict[str, int]] = {
    GuideFlag.STARRED.tag: 0,
    GuideFlag.USER_CONTRIBUTED.tag: 1,
    GuideFlag.ARCHIVED.tag: 2,
    GuideFlag.IN_PROGRESS.tag: 3,
    GuideFlag.MISSING_IMAGES.tag: 4,
    GuideFlag.MISSING_STEPS.tag: 5,
    GuideFlag.INTRODUCTION_ISSUES.tag: 6,
    GuideFlag.NO_DETAILS.tag: 7,
}
