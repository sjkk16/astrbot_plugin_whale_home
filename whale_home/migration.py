"""Validate before migrating. V1 layouts are read only, never silently discarded on error."""
from __future__ import annotations

from copy import deepcopy

from .legacy_layout import validate_layout
from .legacy_v1 import Archive as LegacyArchive
from .legacy_v1 import HomeState as LegacyHome
from .models import Archive, HomeState
from .rules import validate_state


def load_state(data: dict) -> tuple[HomeState, bool]:
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        raise ValueError("missing or invalid state version")
    version = data["schema_version"]
    if version == 2:
        state = HomeState.model_validate(data)
        validate_state(state)
        return state, False
    if version != 1:
        raise ValueError("unsupported state version")
    old = LegacyHome.model_validate(data)
    validate_layout(old)
    upgraded = old.model_dump(mode="json")
    upgraded["schema_version"] = 2
    upgraded["version"] += 1
    upgraded["world_version"] += 1
    upgraded["settings"]["autonomous_enabled"] = False
    upgraded["settings"]["character_style"] = "portrait"
    character = upgraded["character"]
    character.pop("position")
    character.update(location="window", last_path=[], movement_id="",
                     activity="idle", activity_target="")
    for item in upgraded["instances"]:
        item["position"] = None
    state = HomeState.model_validate(upgraded)
    validate_state(state)
    return state, True


def load_archive(data: dict) -> Archive:
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        raise ValueError("invalid archive version")
    if data["schema_version"] == 1:
        old = LegacyArchive.model_validate(data)
        state, _ = load_state(old.state.model_dump(mode="json"))
        data = old.model_dump(mode="json")
        data.update(schema_version=2, state=state.model_dump(mode="json"))
    elif data["schema_version"] != 2:
        raise ValueError("unsupported archive version")
    else:
        data = deepcopy(data)
        if not isinstance(data.get("state"), dict) or data["state"].get("schema_version") != 2:
            raise ValueError("inconsistent archive state version")
    archive = Archive.model_validate(data)
    validate_state(archive.state)
    return archive
