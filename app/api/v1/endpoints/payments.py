# app/api/v1/endpoints/payments.py
import hashlib
import hmac
from decimal import Decimal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.payment import Payment
from app.models.user import User
from app.schemas.payment import (
    PaymentOrderCreate,
    PaymentOrderOut,
    PaymentVerifyOut,
    PaymentVerifyRequest,
)

router = APIRouter()


def _validate_razorpay_credentials() -> None:
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay credentials are not configured.",
        )


@router.post(
    "/create-order",
    response_model=PaymentOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Razorpay order for a paid course",
)
def create_order(
    request: PaymentOrderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOrderOut:
    course = db.get(Course, request.course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if course.status != "published" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot purchase an unpublished course.",
        )

    # Block a second purchase: this user already has a paid payment for this course,
    # or is already enrolled (e.g. enrolled manually by an admin).
    already_paid = (
        db.query(Payment.id)
        .filter(
            Payment.user_id == current_user.id,
            Payment.course_id == course.id,
            Payment.status == "paid",
        )
        .first()
    )
    already_enrolled = (
        db.query(Enrollment.id)
        .filter(
            Enrollment.user_id == current_user.id,
            Enrollment.course_id == course.id,
            Enrollment.status != "cancelled",
        )
        .first()
    )
    if already_paid is not None or already_enrolled is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already purchased this course.",
        )

    amount_paise = int((course.price * Decimal("100")).to_integral_value())
    if amount_paise < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only paid courses can be purchased through Razorpay.",
        )

    _validate_razorpay_credentials()
    try:
        response = httpx.post(
            "https://api.razorpay.com/v1/orders",
            json={
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"vl-{UUID(str(current_user.id)).hex[:12]}-{UUID(str(course.id)).hex[:12]}",
            },
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach Razorpay. Please try again.",
        ) from exc

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Razorpay authentication failed.",
        )
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay is unavailable. Please try again.",
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Razorpay rejected the order request.",
        )

    try:
        order = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay returned an invalid order response.",
        ) from exc
    if not isinstance(order, dict) or not order.get("id"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay returned an invalid order response.",
        )

    payment = Payment(
        user_id=current_user.id,
        course_id=course.id,
        amount=course.price,
        currency="INR",
        razorpay_order_id=order["id"],
        status="created",
    )
    db.add(payment)
    db.commit()

    return PaymentOrderOut(
        order_id=order["id"],
        amount=amount_paise,
        currency="INR",
        key_id=settings.RAZORPAY_KEY_ID,
    )


@router.post(
    "/verify-payment",
    response_model=PaymentVerifyOut,
    summary="Verify a Razorpay payment signature",
)
def verify_payment(
    request: PaymentVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentVerifyOut:
    _validate_razorpay_credentials()
    payment = (
        db.query(Payment)
        .filter(
            Payment.razorpay_order_id == request.razorpay_order_id,
            Payment.user_id == current_user.id,
        )
        .first()
    )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment order not found for the authenticated user.",
        )

    generated_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{request.razorpay_order_id}|{request.razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(generated_signature, request.razorpay_signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment signature verification failed.",
        )

    payment.razorpay_payment_id = request.razorpay_payment_id
    payment.razorpay_signature = request.razorpay_signature
    payment.status = "paid"
    db.commit()

    return PaymentVerifyOut(
        success=True,
        order_id=request.razorpay_order_id,
        payment_id=request.razorpay_payment_id,
    )