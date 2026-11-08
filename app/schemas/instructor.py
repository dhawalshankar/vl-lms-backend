# app/schemas/instructor.py
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


def _clean_url(v: Optional[str]) -> str:
    """Empty is fine; otherwise must be an http(s) URL (blocks javascript:, data:, etc.)."""
    v = (v or "").strip()
    if v and not v.lower().startswith(("http://", "https://")):
        raise ValueError("Must start with http:// or https://")
    return v


def _mask(v: Optional[str]) -> str:
    """Show only the last 4 characters of a sensitive value."""
    v = (v or "").strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "•" * len(v)
    return "•" * (len(v) - 4) + v[-4:]


class InstructorProfileIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    title: str = Field("Language Educator & Linguistic Mentor", max_length=200)
    bio: str = Field("Passionate about making Indian regional languages accessible.", max_length=2000)
    languages: List[str] = ["Hindi", "English"]
    experienceYears: int = Field(5, ge=0, le=80)
    avatarUrl: Optional[str] = None  # None = preserve existing photo; "" = clear it
    twitter: Optional[str] = Field("", max_length=255)
    linkedin: Optional[str] = Field("", max_length=255)
    youtube: Optional[str] = Field("", max_length=255)
    website: Optional[str] = Field("", max_length=255)
    upiId: Optional[str] = Field("", max_length=100)
    bankAccount: Optional[str] = Field("", max_length=100)

    @field_validator("avatarUrl", "twitter", "linkedin", "youtube", "website")
    @classmethod
    def _urls(cls, v: Optional[str]) -> str:
        return _clean_url(v)


class _ProfileFields(BaseModel):
    """Public-safe fields. camelCase names for the frontend, read from snake_case ORM attrs."""

    name: str
    title: str
    bio: str
    languages: List[str] = []
    experienceYears: int = Field(5, validation_alias=AliasChoices("experience_years", "experienceYears"))
    avatarUrl: Optional[str] = Field("", validation_alias=AliasChoices("avatar_url", "avatarUrl"))
    twitter: Optional[str] = ""
    linkedin: Optional[str] = ""
    youtube: Optional[str] = ""
    website: Optional[str] = ""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class InstructorProfileOut(_ProfileFields):
    """The instructor's OWN profile (dashboard). Includes payout details, bank account masked."""

    upiId: Optional[str] = Field("", validation_alias=AliasChoices("upi_id", "upiId"))
    bankAccount: Optional[str] = Field("", validation_alias=AliasChoices("bank_account", "bankAccount"))

    @field_validator("bankAccount")
    @classmethod
    def _mask_bank(cls, v: Optional[str]) -> str:
        return _mask(v)


class InstructorPublicOut(_ProfileFields):
    """Public instructor page. NEVER add payout details or commission here."""

    userId: UUID = Field(validation_alias=AliasChoices("user_id", "userId"))


class InstructorSalesCourseOut(BaseModel):
    """Aggregate sales for one course. Contains no student or payment identity data."""

    courseId: UUID
    courseTitle: str
    coursePrice: Decimal
    currency: str
    salesCount: int
    totalRevenue: Decimal


class InstructorSalesOut(BaseModel):
    """The authenticated instructor's aggregate course sales."""

    totalCourses: int
    totalSales: int
    totalRevenue: Decimal
    courses: List[InstructorSalesCourseOut]