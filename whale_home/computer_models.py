"""Validated computer settings and the finite browser operation protocol."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from .models import Model


class SitePermission(Model):
    domain: str
    account: str = Field(default="", max_length=100)
    authenticated_read: bool = False
    like: bool = False
    favorite: bool = False

    @field_validator("domain")
    @classmethod
    def hostname(cls, value: str) -> str:
        value = value.strip().lower().encode("idna").decode("ascii")
        if len(value) > 253 or not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", value):
            raise ValueError("请输入精确域名，不含协议、端口或通配符")
        return value


class ComputerPreferences(Model):
    enabled: bool = False
    provider_id: str = Field(default="", max_length=160)
    vision_consent: bool = False
    autonomous_enabled: bool = False
    mode: Literal["interest", "focused", "extended"] = "interest"
    interests: str = Field(default="", max_length=2000)
    topics: str = Field(default="", max_length=2000)
    domains: list[str] = Field(default_factory=list, max_length=30)
    start_hour: int = Field(default=8, ge=0, le=23)
    end_hour: int = Field(default=23, ge=0, le=24)
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    daily_runs: int = Field(default=6, ge=1, le=24)
    extended_daily_runs: int = Field(default=2, ge=1, le=8)
    minutes: int = Field(default=5, ge=1, le=30)
    steps: int = Field(default=20, ge=1, le=100)
    extended_minutes: int = Field(default=30, ge=1, le=60)
    extended_steps: int = Field(default=80, ge=1, le=200)
    daily_calls: int = Field(default=200, ge=1, le=1000)
    search_engine: Literal["bing", "duckduckgo"] = "bing"
    sites: list[SitePermission] = Field(default_factory=list, max_length=100)

    @field_validator("domains")
    @classmethod
    def domains_valid(cls, values: list[str]) -> list[str]:
        return sorted({SitePermission(domain=value).domain for value in values})

    @field_validator("sites")
    @classmethod
    def unique_sites(cls, values: list[SitePermission]) -> list[SitePermission]:
        if len({value.domain for value in values}) != len(values):
            raise ValueError("网站不能重复")
        return values


class BrowserAction(Model):
    action: Literal[
        "search",
        "open",
        "read",
        "click",
        "fill",
        "scroll",
        "back",
        "tab",
        "close_tab",
        "finish",
        "ask_user",
    ]
    target: str = Field(default="", max_length=2500)
    text: str = Field(default="", max_length=8000)
    intent: Literal["read", "like", "favorite", "comment", "publish", "message"] = "read"
    new_tab: bool = False
    summary: str = Field(default="", max_length=6000)
    citations: list[str] = Field(default_factory=list, max_length=30)
    memories: list[str] = Field(default_factory=list, max_length=3)
    interest: str = Field(default="", max_length=500)


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().encode("idna").decode("ascii")
