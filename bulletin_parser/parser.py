"""
Bulletin parser: bulletin text -> structured Bulletin.

We use Claude (claude-opus-4-5 by default) with a strict JSON schema
derived from `schema.Bulletin` and ask it to extract every field. Two
features of the Anthropic API make this much more reliable than naive
prompting:

1. `tool_use` with a tool whose input schema is the Pydantic schema.
   The model is constrained to produce valid JSON matching the schema.
2. We pass the bulletin text as a user message and a focused system
   prompt that tells the model the conventions of Catholic bulletins
   (mass intentions phrasing, schedule exception phrasing, etc.).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from .schema import Bulletin


DEFAULT_MODEL = "claude-opus-4-5"

SYSTEM_PROMPT = """You are a parser for Catholic parish bulletins. You read the raw text of a weekly bulletin and produce a structured JSON representation by calling the `record_bulletin` tool.

CONVENTIONS YOU MUST KNOW:

1. **Mass schedules** are usually presented as recurring weekly times. Watch for parenthetical exceptions like "temporary until Pentecost, May 24" or "(no Mass during summer)" — these become `schedule_exceptions`, NOT recurring slots. Bilingual parishes list the language next to each time; default to English if unspecified.

2. **Mass intentions** follow patterns like:
   - "For [Name] by [Requester]" — intention_for=Name, requested_by=Requester
   - "For the eternal rest of [Name] by [Requester]" — same, is_deceased=true
   - "For [Name] - intention requested by [Requester]" — same
   - "For all mothers" (Mother's Day), "For the parish" — intention_for as written, no requested_by
   The bulletin lists these day by day. Each gets its own MassIntention record with the correct date and time. If a day lists multiple intentions at the same Mass time, create one record per intention.

3. **Schedule exceptions** to extract:
   - "Temporary [time] Mass until [date]" → kind=added, with end_date
   - "No [day] Mass on [date]" → kind=cancelled
   - "[time] Mass moved to [new time] on [date]" → kind=moved
   - Holy Day schedules, retreat-week schedules, etc.

4. **Announcements**: each distinct section/blurb is one Announcement. Strip decorative emoji from the body but preserve meaning. Assign `priority`:
   - 1-3: time-sensitive events this week, urgent safety notices, schedule changes
   - 4-6: ongoing programs (book club, marriage prep), recent appeals
   - 7-10: evergreen content (gift shop, perpetual fundraising, "follow us on Instagram")
   Pick the closest `category`. "Victim assistance" / safeguarding notices are `safety`. Stewardship campaigns and recurring giving are `stewardship`.

5. **Locations**: if the bulletin covers multiple worship sites (e.g., a parish with two churches), create a Location for each with stable ids like "main", "secondary", or short slugs. Default single-location parishes to id="main". Every RecurringSlot, ScheduleException, MassIntention, and Collection must reference one of these location ids.

6. **Liturgical day**: extract the Sunday name (e.g., "Sixth Sunday of Easter") and the reading citations. Do NOT copy the full text of the readings — citations only.

7. **Dates and times**: use ISO format. Times are 24-hour. If a year isn't given, infer from the bulletin date.

8. **Be exhaustive but not inventive**: extract everything that's in the bulletin. Do not invent contact details, prices, or dates that aren't stated. Use null for missing fields.

After calling the tool, do not produce any other output."""


def _bulletin_tool_schema() -> dict[str, Any]:
    """Generate the Anthropic tool-use schema from the Pydantic model."""
    schema = Bulletin.model_json_schema()
    # Anthropic tool schemas use the same JSON Schema dialect Pydantic emits.
    # We strip `parser_version`, `parsed_at`, `raw_text_sha256` from the model's
    # responsibility — we set those ourselves after extraction.
    properties = schema.get("properties", {})
    for k in ("parser_version", "parsed_at", "raw_text_sha256"):
        properties.pop(k, None)
    required = [r for r in schema.get("required", []) if r in properties]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "$defs": schema.get("$defs", {}),
    }


def parse_bulletin(
    text: str,
    *,
    model: str = DEFAULT_MODEL,
    client: Any | None = None,
) -> Bulletin:
    """
    Parse a bulletin's raw text into a structured Bulletin.

    Args:
        text: The bulletin text (already extracted from PDF).
        model: Anthropic model to use.
        client: An anthropic.Anthropic client. If None, one is constructed
                (requires ANTHROPIC_API_KEY in environment).

    Raises:
        RuntimeError: If the model fails to call the tool.
        ValidationError: If the model's output doesn't conform to the schema.
    """
    if client is None:
        import anthropic
        client = anthropic.Anthropic()

    tool_schema = _bulletin_tool_schema()

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[
            {
                "name": "record_bulletin",
                "description": (
                    "Record the fully extracted structured representation "
                    "of the parish bulletin. Call exactly once."
                ),
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": "record_bulletin"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is the raw text of a Catholic parish bulletin. "
                    "Extract it into structured form by calling `record_bulletin`.\n\n"
                    f"---BEGIN BULLETIN---\n{text}\n---END BULLETIN---"
                ),
            }
        ],
    )

    # Find the tool_use block
    tool_block = next(
        (b for b in response.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            "Model did not call record_bulletin. "
            f"Response: {response.content!r}"
        )

    payload = tool_block.input
    # Inject the metadata we manage ourselves
    payload["raw_text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload["parsed_at"] = datetime.now(timezone.utc).isoformat()

    try:
        return Bulletin.model_validate(payload)
    except ValidationError as e:
        # Surface the raw payload alongside the error for debugging
        raise ValidationError.from_exception_data(
            title=e.title,
            line_errors=e.errors(),  # type: ignore[arg-type]
        ) from e


def to_json(bulletin: Bulletin) -> str:
    """Serialize a Bulletin to indented JSON."""
    return json.dumps(
        bulletin.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
        default=str,
    )
