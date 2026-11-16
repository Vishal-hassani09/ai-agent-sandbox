import asyncio
import html
import logging
import random
import secrets
import smtplib
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db
from app.schemas.session_schemas import (
    GenerateOtpRequest,
    GenerateOtpResponse,
    TokenResponse,
    UserLogin,
    UserRegister,
    VerifyCaptchaRequest,
    VerifyCaptchaResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Auth"])

OTP_TTL_SECONDS = 600          # 10 minutes
CAPTCHA_TTL_SECONDS = 300      # 5 minutes
WINDOW_RESET_SECONDS = 1800    # 30 minutes cooldown after rate limit
FREE_OTP_ATTEMPTS = 3          # Attempts 1-3 send OTP directly; 4th requires CAPTCHA
MAX_CAPTCHA_RESENDS = 5        # Max CAPTCHA refreshes before 429 rate limit
MAX_OTP_GUESSES = 5            # Max wrong OTP guesses per code


@dataclass
class CaptchaChallenge:
    captcha_id: str
    answer: str
    svg: str
    expires_at: float


@dataclass
class RegistrationFlowState:
    email: str
    otp_attempts: int = 0
    captcha_resends: int = 0
    captcha_solved: bool = False
    active_captcha: Optional[CaptchaChallenge] = None
    otp_code: Optional[str] = None
    otp_expires_at: float = 0.0
    otp_wrong_guesses: int = 0
    window_started_at: float = 0.0


# In-memory verification store keyed by normalized email
_reg_flows: Dict[str, RegistrationFlowState] = {}


def _get_or_create_flow(email: str) -> RegistrationFlowState:
    now = time.time()
    norm_email = email.strip().lower()
    flow = _reg_flows.get(norm_email)
    if flow is None or (now - flow.window_started_at) > WINDOW_RESET_SECONDS:
        flow = RegistrationFlowState(email=norm_email, window_started_at=now)
        _reg_flows[norm_email] = flow
    return flow


def _generate_captcha_challenge() -> CaptchaChallenge:
    """Creates a clean SVG CAPTCHA challenge with a 5-character alphanumeric code."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(5))
    cid = str(uuid.uuid4())

    # Build randomized SVG noise lines and rotated characters
    lines_svg = []
    colors = ["#d97757", "#38bdf8", "#a78bfa", "#4ade80", "#fbbf24"]
    for _ in range(5):
        x1, y1 = random.randint(0, 180), random.randint(0, 56)
        x2, y2 = random.randint(0, 180), random.randint(0, 56)
        col = random.choice(colors)
        lines_svg.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{col}" stroke-width="1.3" opacity="0.45" />'
        )

    chars_svg = []
    for idx, ch in enumerate(code):
        x = 22 + idx * 30
        y = random.randint(33, 42)
        rot = random.randint(-18, 18)
        col = random.choice(["#f5f5f4", "#fde68a", "#bae6fd", "#fed7aa"])
        chars_svg.append(
            f'<text x="{x}" y="{y}" fill="{col}" font-family="monospace" '
            f'font-size="24" font-weight="bold" '
            f'transform="rotate({rot} {x} {y})">{html.escape(ch)}</text>'
        )

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="56" viewBox="0 0 180 56">'
        '<rect width="180" height="56" rx="8" fill="#141413" stroke="#333330" />'
        + "".join(lines_svg)
        + "".join(chars_svg)
        + "</svg>"
    )
    return CaptchaChallenge(
        captcha_id=cid,
        answer=code,
        svg=svg,
        expires_at=time.time() + CAPTCHA_TTL_SECONDS,
    )


def _send_email_sync(recipient: str, otp_code: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"{otp_code} is your AI Coder verification code"
    msg["From"] = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
    msg["To"] = recipient
    msg.set_content(
        f"Your AI Coder registration verification code is: {otp_code}\n\n"
        "This code will expire in 10 minutes. If you did not request this, you can safely ignore this email."
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


async def _dispatch_otp_email(recipient: str, otp_code: str) -> None:
    """Sends OTP via SMTP if configured, otherwise logs clearly to server console for local dev."""
    if settings.SMTP_HOST and (settings.SMTP_FROM_EMAIL or settings.SMTP_USER):
        try:
            await asyncio.to_thread(_send_email_sync, recipient, otp_code)
            logger.info("Sent OTP email to %s via SMTP", recipient)
            return
        except Exception as err:
            logger.error("Failed to send SMTP email to %s: %s", recipient, err)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to deliver OTP email. Please check SMTP configuration.",
            ) from err

    # Local / dev fallback when SMTP credentials are not configured
    logger.warning("[DEV OTP] Verification code for %s -> %s", recipient, otp_code)
    print(f"\n[AI CODER OTP] Email: {recipient} | Code: {otp_code}\n", flush=True)


async def _issue_and_send_otp(flow: RegistrationFlowState) -> str:
    otp = f"{secrets.randbelow(900000) + 100000}"
    flow.otp_code = otp
    flow.otp_expires_at = time.time() + OTP_TTL_SECONDS
    flow.otp_wrong_guesses = 0
    await _dispatch_otp_email(flow.email, otp)
    return otp


@router.post("/generate-otp", response_model=GenerateOtpResponse)
async def generate_otp(
    payload: GenerateOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1 / Resend OTP:
    - Attempts 1-3: Generates & sends OTP directly.
    - Attempt 4+: Requires CAPTCHA verification before sending OTP.
    - Captcha Resend: Refreshes CAPTCHA up to 5 times, then enforces 429 rate limit.
    """
    norm_email = payload.email.strip().lower()

    existing = await db.execute(select(User).where(User.email == norm_email))
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered. Please sign in instead.",
        )

    flow = _get_or_create_flow(norm_email)

    # Case A: User clicked "Resend CAPTCHA"
    if payload.is_captcha_resend:
        if flow.captcha_resends >= MAX_CAPTCHA_RESENDS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Maximum CAPTCHA resend limit (5) reached. Please wait 30 minutes before trying again.",
            )
        flow.captcha_resends += 1
        flow.captcha_solved = False
        challenge = _generate_captcha_challenge()
        flow.active_captcha = challenge
        return GenerateOtpResponse(
            status="captcha_required",
            message=f"New CAPTCHA generated ({flow.captcha_resends}/{MAX_CAPTCHA_RESENDS} resends used).",
            otp_attempts=flow.otp_attempts,
            captcha_resends=flow.captcha_resends,
            captcha_id=challenge.captcha_id,
            captcha_svg=challenge.svg,
        )

    # Case B: Normal "Send OTP" or "Resend OTP" click
    flow.otp_attempts += 1

    # On 4th+ attempt (or if CAPTCHA is required and not yet solved)
    if flow.otp_attempts > FREE_OTP_ATTEMPTS and not flow.captcha_solved:
        if flow.captcha_resends >= MAX_CAPTCHA_RESENDS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many verification attempts. Please wait 30 minutes before trying again.",
            )
        challenge = _generate_captcha_challenge()
        flow.active_captcha = challenge
        return GenerateOtpResponse(
            status="captcha_required",
            message="Please complete the CAPTCHA challenge to send another OTP.",
            otp_attempts=flow.otp_attempts,
            captcha_resends=flow.captcha_resends,
            captcha_id=challenge.captcha_id,
            captcha_svg=challenge.svg,
        )

    # Reset captcha_solved after using it so any subsequent resend requires a fresh CAPTCHA
    if flow.otp_attempts > FREE_OTP_ATTEMPTS:
        flow.captcha_solved = False

    await _issue_and_send_otp(flow)
    return GenerateOtpResponse(
        status="otp_sent",
        message=f"Verification code sent to {norm_email}.",
        otp_attempts=flow.otp_attempts,
        captcha_resends=flow.captcha_resends,
    )


@router.post("/verify-captcha", response_model=VerifyCaptchaResponse)
async def verify_captcha(payload: VerifyCaptchaRequest):
    """
    Verifies the CAPTCHA answer and immediately generates + sends the OTP upon success.
    """
    norm_email = payload.email.strip().lower()
    flow = _reg_flows.get(norm_email)
    if not flow or not flow.active_captcha:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active CAPTCHA challenge found. Please request a new code.",
        )

    challenge = flow.active_captcha
    if time.time() > challenge.expires_at:
        flow.active_captcha = None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CAPTCHA expired. Click 'Resend CAPTCHA' to get a new one.",
        )

    if challenge.captcha_id != payload.captcha_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CAPTCHA session. Please refresh the CAPTCHA.",
        )

    if payload.captcha_answer.strip().upper() != challenge.answer.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect CAPTCHA text. Please try again or click 'Resend CAPTCHA'.",
        )

    # CAPTCHA verified -> consume challenge, generate and send OTP immediately
    flow.active_captcha = None
    flow.captcha_solved = True
    await _issue_and_send_otp(flow)

    return VerifyCaptchaResponse(
        status="otp_sent",
        message=f"CAPTCHA verified! A new OTP has been sent to {norm_email}.",
    )


@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(payload: VerifyOtpRequest):
    """
    Verifies the 6-digit OTP and issues a short-lived verification_token required to set a password.
    """
    norm_email = payload.email.strip().lower()
    flow = _reg_flows.get(norm_email)
    if not flow or not flow.otp_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active OTP found for this email. Please request a code first.",
        )

    if time.time() > flow.otp_expires_at:
        flow.otp_code = None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired. Please click 'Resend OTP' to get a new code.",
        )

    if flow.otp_wrong_guesses >= MAX_OTP_GUESSES:
        flow.otp_code = None
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many incorrect OTP guesses. Please request a new OTP.",
        )

    if payload.otp.strip() != flow.otp_code:
        flow.otp_wrong_guesses += 1
        remaining = max(0, MAX_OTP_GUESSES - flow.otp_wrong_guesses)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OTP code ({remaining} attempts remaining).",
        )

    # OTP verified -> issue short-lived registration verification token
    flow.otp_code = None
    verification_token = create_access_token(
        {"sub": norm_email, "email": norm_email, "purpose": "email_verification"},
        expires_delta=timedelta(minutes=15),
    )
    return VerifyOtpResponse(
        verified=True,
        verification_token=verification_token,
        message="Email verified! You may now set your password.",
    )


@router.post("/register", response_model=TokenResponse)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    norm_email = payload.email.strip().lower()

    # Validate the OTP verification_token before creating the account
    decoded = decode_access_token(payload.verification_token)
    if (
        not decoded
        or decoded.get("purpose") != "email_verification"
        or (decoded.get("email") or "").lower() != norm_email
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required before setting a password.",
        )

    existing = await db.execute(select(User).where(User.email == norm_email))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=norm_email,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Clean up registration state
    _reg_flows.pop(norm_email, None)

    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user_id=user.id, email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    norm_email = payload.email.strip().lower()
    res = await db.execute(select(User).where(User.email == norm_email))
    user = res.scalars().first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, user_id=user.id, email=user.email)