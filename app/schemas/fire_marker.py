from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FireMarkerCreate(BaseModel):
    longitude: float
    latitude: float
    marked_at: Optional[datetime] = None
    fire_count: int = Field(..., ge=1)
    source: Optional[str] = Field(None, max_length=32)
    note: Optional[str] = None
    status: str = Field("pending", pattern="^(pending|handling|extinguished)$")
    level: str = Field("low", pattern="^(low|medium|high)$")
    cause: str = Field("unknown", pattern="^(human|lightning|farming|unknown)$")
    region: Optional[str] = Field(None, max_length=64)

    @field_validator("longitude")
    @classmethod
    def check_lng(cls, v: float) -> float:
        if v < -180.0 or v > 180.0:
            raise ValueError("经度必须在 -180～180 之间")
        return v

    @field_validator("latitude")
    @classmethod
    def check_lat(cls, v: float) -> float:
        if v < -90.0 or v > 90.0:
            raise ValueError("纬度必须在 -90～90 之间")
        return v


class FireMarkerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    longitude: float
    latitude: float
    marked_at: datetime
    fire_count: int
    source: Optional[str]
    note: Optional[str]
    created_at: datetime
    updated_at: datetime
    status: str
    level: str
    cause: str
    region: Optional[str]
    reporter_user_id: Optional[str]
    reporter_username: Optional[str]

    @field_validator("longitude", "latitude", mode="before")
    @classmethod
    def decimal_to_float(cls, v: object) -> object:
        if isinstance(v, Decimal):
            return float(v)
        return v


class FireMarkerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    longitude: float
    latitude: float
    marked_at: datetime
    fire_count: int
    source: Optional[str]
    note: Optional[str]
    created_at: datetime
    updated_at: datetime
    status: str
    level: str
    cause: str
    region: Optional[str]

    @field_validator("longitude", "latitude", mode="before")
    @classmethod
    def decimal_to_float(cls, v: object) -> object:
        if isinstance(v, Decimal):
            return float(v)
        return v


class FireMarkerPageData(BaseModel):
    items: List[FireMarkerListItem]
    total: int
    page: int
    page_size: int


class FireMarkerPatchBody(BaseModel):
    note: Optional[str] = None
    fire_count: Optional[int] = Field(None, ge=1)
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    status: Optional[str] = Field(
        None, pattern="^(pending|handling|extinguished)$"
    )
    level: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    cause: Optional[str] = Field(None, pattern="^(human|lightning|farming|unknown)$")

    @field_validator("longitude")
    @classmethod
    def check_lng_patch(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v < -180.0 or v > 180.0:
            raise ValueError("经度必须在 -180～180 之间")
        return v

    @field_validator("latitude")
    @classmethod
    def check_lat_patch(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v < -90.0 or v > 90.0:
            raise ValueError("纬度必须在 -90～90 之间")
        return v


class FireMarkerStatusPatchBody(BaseModel):
    status: str = Field(..., pattern="^(pending|handling|extinguished)$")
