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
