import json
import re
from datetime import date, time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from offices import OFFICES

# Settings are persisted here so they survive restarts (mount ./data as a volume)
SETTINGS_FILE = Path("data/settings.json")
# Whether the user left the bot running, so it can resume after a server restart
SESSION_FILE = Path("data/session.json")

DNI_NIE_REGEX = re.compile(r"^[XYZ]?\d{7,8}[A-Z]$")
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class DateRange(BaseModel):
    """A preferred date with a time window to book the appointment in."""

    date: date
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def check_time_window(self):
        if self.start_time >= self.end_time:
            raise ValueError("start time must be before end time")
        return self


class Settings(BaseModel):
    office_ids: list[int] = Field(min_length=1)
    # What the appointment is for; decides which area is selected at each office
    procedure: Literal["matriculacion", "vehiculos"] = "matriculacion"
    check_period_minutes: int = Field(ge=5, le=60)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    dni: str
    email: str
    # Empty means "book the first available date"
    date_ranges: list[DateRange] = []

    @field_validator("office_ids")
    @classmethod
    def check_office_ids(cls, value):
        unknown = [office_id for office_id in value if office_id not in OFFICES]
        if unknown:
            raise ValueError(f"unknown office IDs: {unknown}")
        return value

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("dni")
    @classmethod
    def check_dni(cls, value):
        value = value.strip().upper()
        if not DNI_NIE_REGEX.match(value):
            raise ValueError("must be a valid DNI or NIE (e.g. 12345678A, X1234567B)")
        return value

    @field_validator("email")
    @classmethod
    def check_email(cls, value):
        value = value.strip()
        if not EMAIL_REGEX.match(value):
            raise ValueError("must be a valid email address")
        return value


def load_settings() -> Settings | None:
    if not SETTINGS_FILE.exists():
        return None
    return Settings.model_validate_json(SETTINGS_FILE.read_text())


def save_settings(settings: Settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(settings.model_dump_json(indent=2))


def load_session_active() -> bool:
    if not SESSION_FILE.exists():
        return False
    return json.loads(SESSION_FILE.read_text()).get("active", False)


def save_session_active(active: bool):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({"active": active}))
