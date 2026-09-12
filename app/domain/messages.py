"""What the bot says, in Persian, as templates (PHASE0 §36).

Templates are the fallback strategy and the system must work with nothing else;
AI may rewrite these later but may never decide eligibility, membership or
revocation. Keeping the wording here — not inside handlers or the monitoring
job — means the copy can be reviewed and changed by someone who does not read
Python, and that the same words are used wherever a situation recurs.

Amounts are formatted from Decimal with explicit quantisation rather than
f-string floats: a member told they are "0.1 short" when they are 0.09999999
short will send that screenshot to support.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

WELCOME = (
    "سلام {name} 👋\n\n"
    "برای دسترسی به کانال VIP، از طریق لینک زیر در صرافی ثبت‌نام کنید "
    "و سپس UID حساب خود را همین‌جا بفرستید:\n\n"
    "{referral_link}\n\n"
    "UID یک عدد ۹ رقمی است."
)

CHOOSE_MARKET = "کدام بازار را می‌خواهید؟"

ASK_FOR_UID = "لطفاً UID حساب صرافی خود را بفرستید (یک عدد ۹ رقمی)."

INVALID_UID = (
    "این UID معتبر نیست. UID یک عدد ۹ رقمی است — لطفاً دوباره بررسی کنید و بفرستید."
)

UID_CLAIMED = (
    "این UID قبلاً برای کاربر دیگری ثبت شده است.\n"
    "اگر فکر می‌کنید اشتباهی رخ داده، با پشتیبانی تماس بگیرید."
)

NOT_REGISTERED = (
    "حساب شما زیرمجموعه رفرال ما نیست.\n\n"
    "برای واجد شرایط شدن باید از طریق لینک زیر ثبت‌نام کنید:\n{referral_link}\n\n"
    "اگر تازه ثبت‌نام کرده‌اید، چند دقیقه صبر کنید و دوباره امتحان کنید."
)

INSUFFICIENT_BALANCE = (
    "حساب شما تأیید شد، اما موجودی واریزی کافی نیست.\n\n"
    "حداقل لازم: {minimum} دلار\n"
    "موجودی فعلی شما: {balance} دلار\n"
    "کسری: {shortfall} دلار\n\n"
    "پس از واریز، دوباره UID خود را بفرستید."
)

PROVIDER_UNAVAILABLE = (
    "در حال حاضر امکان بررسی حساب شما وجود ندارد.\n"
    "این مشکل از سمت ماست، نه شما — لطفاً چند دقیقه دیگر دوباره تلاش کنید."
)

NOT_CONFIGURED = (
    "این بخش هنوز راه‌اندازی نشده است. لطفاً با پشتیبانی تماس بگیرید."
)

INVITED = (
    "تبریک 🎉 دسترسی شما تأیید شد.\n\n"
    "با لینک زیر به کانال VIP بپیوندید:\n{invite_link}\n\n"
    "این لینک یک‌بارمصرف است و فقط برای شما کار می‌کند."
)

ALREADY_MEMBER = (
    "شما همچنان عضو فعال کانال VIP هستید.\n\n"
    "اگر به لینک نیاز دارید:\n{invite_link}"
)

COMPLIANCE_WARNING = (
    "⚠️ هشدار {warning_number} از {max_warnings}\n\n"
    "شرایط عضویت شما در کانال VIP دیگر برقرار نیست.\n"
    "{reason_text}\n\n"
    "در صورت عدم رفع، دسترسی شما لغو خواهد شد."
)

MEMBERSHIP_REVOKED = (
    "دسترسی شما به کانال VIP لغو شد.\n\n"
    "{reason_text}\n\n"
    "پس از رفع شرایط، می‌توانید دوباره UID خود را بفرستید تا بررسی شود."
)

MEMBERSHIP_RESTORED = (
    "✅ شرایط عضویت شما دوباره برقرار شد. هشدارهای قبلی پاک شدند."
)

REASON_TEXT = {
    "NOT_REGISTERED": "حساب شما دیگر زیرمجموعه رفرال ما نیست.",
    "INSUFFICIENT_BALANCE": "موجودی واریزی شما به زیر حد مجاز رسیده است.",
    "INSUFFICIENT_TRADING": "در دوره اخیر معامله واجد شرایط ثبت نشده است.",
}


def format_amount(value: Decimal, places: int = 2) -> str:
    """Two decimal places, rounded the way that does not mislead.

    Shortfalls round UP: telling someone they need 0.10 more when they need
    0.101 sends them back with a second failed attempt. Rounding the
    requirement in the user's disfavour is the honest direction.
    """
    quantum = Decimal(1).scaleb(-places)
    return str(value.quantize(quantum, rounding=ROUND_CEILING).normalize())
