# app/api/v1/endpoints/instructor.py
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_optional_current_user, require_role
from app.core.database import get_db
from app.models.course import Course
from app.models.instructor import InstructorProfile
from app.models.payment import Payment
from app.models.user import User
from app.schemas.instructor import (
    InstructorProfileIn,
    InstructorProfileOut,
    InstructorPublicOut,
    InstructorSalesCourseOut,
    InstructorSalesOut,
)

router = APIRouter()

DEFAULT_TITLE = "Language Educator & Linguistic Mentor"
DEFAULT_BIO = (
    "Passionate about making Indian regional languages accessible to learners "
    "across India and the global diaspora."
)


def _own_out(profile: InstructorProfile) -> InstructorProfileOut:
    """Owner/admin view. Includes payout details (bank account is masked by the schema)."""
    return InstructorProfileOut(
        name=profile.name,
        title=profile.title,
        bio=profile.bio,
        languages=profile.languages or ["Hindi", "English"],
        experienceYears=profile.experience_years,
        avatarUrl=profile.avatar_url or "",
        twitter=profile.twitter or "",
        linkedin=profile.linkedin or "",
        youtube=profile.youtube or "",
        website=profile.website or "",
        upiId=profile.upi_id or "",
        bankAccount=profile.bank_account or "",
    )


def _public_out(profile: InstructorProfile) -> InstructorPublicOut:
    """Public view. No payout details, ever."""
    return InstructorPublicOut(
        userId=profile.user_id,
        name=profile.name,
        title=profile.title,
        bio=profile.bio,
        languages=profile.languages or ["Hindi", "English"],
        experienceYears=profile.experience_years,
        avatarUrl=profile.avatar_url or "",
        twitter=profile.twitter or "",
        linkedin=profile.linkedin or "",
        youtube=profile.youtube or "",
        website=profile.website or "",
    )


def _has_published_course(db: Session, user_id: UUID) -> bool:
    # NOTE: confirm Course.instructor_id / Course.status names against app/models/course.py
    return (
        db.query(Course.id)
        .filter(Course.instructor_id == user_id, Course.status == "published")
        .first()
        is not None
    )


@router.get(
    "/profile",
    response_model=None,
    summary="Get instructor profile (own = full, public = only if they have a published course)",
)
def get_instructor_profile(
    user_id: Optional[str] = Query(None, description="Optional instructor user id"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    target_id: Optional[UUID] = None
    if user_id:
        try:
            target_id = UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id")
    elif current_user:
        target_id = current_user.id

    if not target_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructor not found")

    is_owner = bool(current_user and current_user.id == target_id)
    is_admin = bool(current_user and current_user.role == "admin")

    profile = (
        db.query(InstructorProfile)
        .filter(InstructorProfile.user_id == target_id)
        .first()
    )

    # Someone else's profile: public view, and only if they have at least one published course.
    # Admins can always view (they see the full profile).
    if not is_owner and not is_admin:
        if not profile or not _has_published_course(db, target_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructor not found")
        return _public_out(profile)

    if profile:
        return _own_out(profile)

    if is_admin and not is_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructor not found")

    # Owner with no saved profile yet: neutral defaults only
    return InstructorProfileOut(
        name=current_user.full_name,
        title=DEFAULT_TITLE,
        bio=DEFAULT_BIO,
        languages=["Hindi", "English"],
        experienceYears=5,
        avatarUrl=current_user.avatar_url or "",
        twitter="",
        linkedin="",
        youtube="",
        website="",
        upiId="",
        bankAccount="",
    )


@router.post(
    "/profile",
    response_model=InstructorProfileOut,
    summary="Save / update instructor profile",
)
def save_instructor_profile(
    payload: InstructorProfileIn,
    current_user: User = Depends(require_role(["instructor", "admin"])),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(InstructorProfile)
        .filter(InstructorProfile.user_id == current_user.id)
        .first()
    )

    avatar = (payload.avatarUrl or "").strip() or None  # empty = clear the photo

    if not profile:
        profile = InstructorProfile(
            user_id=current_user.id,
            name=payload.name,
            title=payload.title,
            bio=payload.bio,
            languages=payload.languages,
            experience_years=payload.experienceYears,
            avatar_url=avatar or current_user.avatar_url,
            twitter=payload.twitter,
            linkedin=payload.linkedin,
            youtube=payload.youtube,
            website=payload.website,
            upi_id=payload.upiId,
            bank_account=payload.bankAccount,
        )
        db.add(profile)
    else:
        profile.name = payload.name
        profile.title = payload.title
        profile.bio = payload.bio
        profile.languages = payload.languages
        profile.experience_years = payload.experienceYears
        profile.avatar_url = avatar
        profile.twitter = payload.twitter
        profile.linkedin = payload.linkedin
        profile.youtube = payload.youtube
        profile.website = payload.website
        profile.upi_id = payload.upiId
        # The form is pre-filled with the MASKED account number. If it comes back
        # masked, keep the real stored value instead of overwriting it.
        if "•" not in (payload.bankAccount or ""):
            profile.bank_account = payload.bankAccount

    # Keep user's full_name and avatar synced
    current_user.full_name = payload.name
    if avatar:
        current_user.avatar_url = avatar

    db.commit()
    db.refresh(profile)

    return _own_out(profile)


@router.get(
    "/sales",
    response_model=InstructorSalesOut,
    summary="Get aggregate sales for the authenticated instructor's courses",
)
def get_instructor_sales(
    current_user: User = Depends(require_role(["instructor", "admin"])),
    db: Session = Depends(get_db),
) -> InstructorSalesOut:
    """Return course sales totals without exposing any student information."""
    courses = (
        db.query(Course)
        .filter(Course.instructor_id == current_user.id)
        .order_by(Course.title)
        .all()
    )

    paid_sales = []
    if courses:
        # One row per (course, student): duplicate paid rows for the same
        # student collapse into one, so "sold" and revenue are both per student.
        per_student = (
            db.query(
                Payment.course_id.label("course_id"),
                Payment.user_id.label("user_id"),
                func.max(Payment.amount).label("amount"),
                func.min(Payment.currency).label("currency"),
            )
            .filter(
                Payment.status == "paid",
                Payment.course_id.in_([course.id for course in courses]),
            )
            .group_by(Payment.course_id, Payment.user_id)
            .subquery()
        )

        paid_sales = (
            db.query(
                per_student.c.course_id.label("course_id"),
                func.count().label("sales_count"),
                func.coalesce(func.sum(per_student.c.amount), 0).label("total_revenue"),
                func.min(per_student.c.currency).label("currency"),
            )
            .group_by(per_student.c.course_id)
            .all()
        )
    sales_by_course = {row.course_id: row for row in paid_sales}

    course_sales = [
        InstructorSalesCourseOut(
            courseId=course.id,
            courseTitle=course.title,
            coursePrice=course.price,
            currency=(
                sales_by_course[course.id].currency
                if course.id in sales_by_course
                else "INR"
            ),
            salesCount=(
                sales_by_course[course.id].sales_count
                if course.id in sales_by_course
                else 0
            ),
            totalRevenue=(
                sales_by_course[course.id].total_revenue
                if course.id in sales_by_course
                else Decimal("0.00")
            ),
        )
        for course in courses
    ]

    return InstructorSalesOut(
        totalCourses=len(course_sales),
        totalSales=sum(course.salesCount for course in course_sales),
        totalRevenue=sum(
            (course.totalRevenue for course in course_sales), Decimal("0.00")
        ),
        courses=course_sales,
    )