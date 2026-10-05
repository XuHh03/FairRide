"""The three model roles. Implement each role as a separate model call."""

from contracts import AdvocateResult, JudgeResult, ReviewInput


def rider_advocate(review: ReviewInput) -> AdvocateResult:
    """Return claims with evidence IDs, policy IDs, and open questions."""
    raise NotImplementedError("Rider Advocate model call has not been added yet")


def driver_advocate(review: ReviewInput) -> AdvocateResult:
    """Return claims with evidence IDs, policy IDs, and open questions."""
    raise NotImplementedError("Driver Advocate model call has not been added yet")


def judge(
    review: ReviewInput,
    rider_argument: AdvocateResult,
    driver_argument: AdvocateResult,
    rebuttals: list[AdvocateResult] | None = None,
) -> JudgeResult:
    """Return a ruling, a specific evidence request, or human review."""
    raise NotImplementedError("Judge model call has not been added yet")
