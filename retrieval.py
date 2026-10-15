"""Bounded advocate-directed reads of local, normalized trip evidence."""

from time import perf_counter

from contracts import EvidenceRequest, ReviewInput, Role


class LocalEvidenceTools:
    def __init__(self, review: ReviewInput):
        self.records = review.evidence
        self.ticket = next(record for record in self.records if record.source == "dispute_ticket")
        self.trip_id = self.ticket.data["trip_id"]
        self.available_sources = sorted({record.source for record in self.records} - {"dispute_ticket"})

    def read(self, trip_id: str, sources: list[str]):
        if trip_id != self.trip_id:
            raise ValueError("Evidence tool cannot access another trip")
        if not sources or any(source not in self.available_sources for source in sources):
            raise ValueError("Evidence tool received an unavailable source")
        return [record.model_copy(deep=True) for record in self.records if record.source in sources]


async def gather_advocate_evidence(review: ReviewInput, role: Role, planner, on_event, on_progress) -> ReviewInput:
    tools = LocalEvidenceTools(review)
    retrieved = set()
    results = []
    name = "Rider Advocate" if role == "rider_advocate" else "Driver Advocate"
    for round_number in range(1, 4):
        on_progress(f"{name}: retrieving evidence (round {round_number}/3)")
        started = perf_counter()
        payload = {
            "role": role, "trip_id": tools.trip_id,
            "complaint": tools.ticket.data["description"],
            "ticket": tools.ticket.model_dump(mode="json"),
            "policy": review.policy.model_dump(mode="json"),
            "available_sources": tools.available_sources,
            "remaining_sources": sorted(set(tools.available_sources) - retrieved),
            "tool_results": results, "rounds_remaining": 4 - round_number,
        }
        event = {"trip_id": tools.trip_id, "sources": [], "purpose": "Select local evidence sources",
                 "round": round_number, "usage": {}}
        try:
            call = await planner(payload)
            event["usage"] = {key: value for key, value in call.usage.items()
                              if key in ("prompt_tokens", "completion_tokens", "total_tokens")
                              and isinstance(value, int) and not isinstance(value, bool)}
            request = EvidenceRequest.model_validate(call.result)
            event.update(request.model_dump(mode="json"))
            records = tools.read(request.trip_id, request.sources)
        except Exception as exc:
            error = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
            event.update(error=error, record_ids=[], duration_ms=round((perf_counter() - started) * 1000))
            on_event(event)
            raise
        event.update(record_ids=[record.id for record in records],
                     duration_ms=round((perf_counter() - started) * 1000))
        on_event(event)
        retrieved.update(request.sources)
        results.append({"trip_id": request.trip_id, "sources": request.sources,
                        "records": [record.model_dump(mode="json") for record in records]})
        if retrieved == set(tools.available_sources):
            on_progress(f"{name}: evidence retrieved; building its argument")
            return review
    raise ValueError(f"{name} exhausted its retrieval budget before reviewing all available sources")
