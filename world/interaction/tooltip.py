"""build_tooltip_text — one short display string from a `HoverInfo`.

Kept separate from `HoverManager` itself since "what data does a hover
need" (HoverManager's job) and "how is it formatted for display"
(this module's job) are different concerns — a future renderer-specific
tooltip widget can format the same `HoverInfo` differently without
touching `HoverManager`.
"""

from world.interaction.models import HoverInfo


def build_tooltip_text(hover_info: HoverInfo) -> str:
    parts = [hover_info.target_id]
    if hover_info.room_info:
        parts.append(hover_info.room_info)
    if hover_info.status:
        parts.append(hover_info.status)
    if hover_info.activity:
        parts.append(hover_info.activity)
    if hover_info.current_event:
        parts.append(hover_info.current_event)
    return " — ".join(parts)
