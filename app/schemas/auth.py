import re

from pydantic import BaseModel, Field, field_validator


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("username")
    @classmethod
    def username_chars(cls, v: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_]+", v):
            raise ValueError("用户名仅允许字母、数字、下划线")
        return v


class LoginBody(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    id: str
    username: str


class RegisterResponseData(BaseModel):
    user: UserPublic


class LoginResponseData(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserPublic
