from __future__ import annotations

from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator


class UavWaypoint(BaseModel):
    longitude: float = Field(..., ge=-180.0, le=180.0)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    # altitude_m is canonical; accept legacy "altitude" from earlier versions.
    altitude_m: Optional[float] = Field(
        None,
        ge=-1000.0,
        le=20000.0,
        validation_alias=AliasChoices("altitude_m", "altitude"),
    )


class UavMissionCreateBody(BaseModel):
    mission_type: Literal["uav", "fleet"]
    waypoints: list[UavWaypoint] = Field(..., min_length=1, max_length=200)
    speed_level: Optional[Literal["low", "medium", "high"]] = None

    @field_validator("waypoints")
    @classmethod
    def _validate_waypoints(cls, v: list[UavWaypoint], info):  # type: ignore[no-untyped-def]
        mission_type = info.data.get("mission_type")
        if mission_type == "uav":
            missing = [i for i, w in enumerate(v) if w.altitude_m is None]
            if missing:
                raise ValueError(
                    f"mission_type=uav 时每个航点必须包含 altitude_m，缺失索引: {missing}"
                )
        return v


class UavMissionCreateOut(BaseModel):
    mission_id: str
