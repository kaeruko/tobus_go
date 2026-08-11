import uuid
from collections.abc import Callable


def assign_candidate_step_ids(
    candidate: dict,
    *,
    id_factory: Callable[[], str] | None = None,
) -> None:
    make_id = id_factory or (lambda: uuid.uuid4().hex)
    seen: set[str] = set()
    for step in candidate.get("steps", []):
        kind = str(step.get("kind") or "unknown")
        step_id = f"step-{kind}-{make_id()}"
        if step_id in seen:
            raise ValueError(f"duplicate generated step_id: {step_id}")
        step["step_id"] = step_id
        seen.add(step_id)
