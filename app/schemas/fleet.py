from __future__ import annotations

from pydantic import BaseModel, Field


class FleetTelemetryBody(BaseModel):
    longitude: float = Field(..., ge=-180.0, le=180.0)
    latitude: float = Field(..., ge=-90.0, le=90.0)

