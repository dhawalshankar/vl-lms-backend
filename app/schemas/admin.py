# app/schemas/admin.py
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.course import CourseCreate


class AdminStatsOut(BaseModel):
    total_users: int  # everyone who has logged in via SSO at least once
    new_users_7d: int
    active_users_7d: int
    active_users_30d: int
    students: int
    instructors: int
    admins: int
    courses_by_status: Dict[str, int]  # draft | pending_review | published | rejected | archived


class AdminUserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    first_login_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    login_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class AdminInstructorOut(BaseModel):
    id: UUID
    full_name: str
    email: str


class AdminCourseOut(BaseModel):
    id: UUID
    title: str
    language: str
    level: str
    status: str
    price: float
    enrolled_count: int
    lessons_count: int
    instructor_id: UUID
    instructor_name: Optional[str] = None
    instructor_email: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    managed_by_admin: bool = False
    created_at: datetime


class AdminCourseCreate(CourseCreate):
    """Create a course on behalf of an existing instructor."""

    instructor_id: UUID
    publish: bool = False  # True = publish immediately (the admin is the approver)


class CourseRejectIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


class UserStatusUpdate(BaseModel):
    is_active: Optional[bool] = None


class DeleteUserOut(BaseModel):
    ok: bool = True


class DeleteCourseOut(BaseModel):
    archived: bool  # True = soft-deleted (had enrollments or payments), False = removed


class AdminInstructorEnrollmentOut(BaseModel):
    instructor_id: UUID
    instructor_name: str
    instructor_email: str
    course_id: UUID
    course_title: str
    course_price: Decimal
    currency: str
    enrollment_count: int
    paid_enrollment_count: int
    total_paid_amount: Decimal


class AdminPaymentOut(BaseModel):
    id: UUID
    amount: Decimal
    currency: str
    status: str
    razorpay_order_id: str
    razorpay_payment_id: Optional[str] = None
    created_at: datetime


class AdminEnrollmentFinancialOut(BaseModel):
    enrollment_id: UUID
    enrolled_at: datetime
    completed_at: Optional[datetime] = None
    enrollment_status: str
    student_id: UUID
    student_name: str
    student_email: str
    course_id: UUID
    course_title: str
    instructor_id: UUID
    instructor_name: str
    course_price: Decimal
    progress_percentage: float
    completed_lessons: int
    total_lessons: int
    payments: List[AdminPaymentOut]