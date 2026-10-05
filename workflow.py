"""Control the order of agent calls and limit review to one rebuttal round."""

from contracts import WorkflowResult


def run_review(case: dict, policy: dict) -> WorkflowResult:
    """Return the final reviewed case and the visible agent activity log."""
    raise NotImplementedError("Agent workflow has not been added yet")
