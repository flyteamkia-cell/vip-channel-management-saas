"""Normalising an exchange UID typed into a Telegram chat.

Persian users type Persian digits. The n8n prototype learned this the hard way
and normalised them inline; here it is a pure function with tests, because it
is the first gate every referral signup passes through and a false rejection
looks to the user like "the bot is broken".
"""

from __future__ import annotations

import re

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TRANSLATION = str.maketrans(
    {
        **{ch: str(i) for i, ch in enumerate(PERSIAN_DIGITS)},
        **{ch: str(i) for i, ch in enumerate(ARABIC_DIGITS)},
    }
)

#: Bitunix UIDs observed in production are nine digits.
BITUNIX_UID_PATTERN = re.compile(r"^\d{9}$")


def normalize_uid(raw: str | None) -> str:
    """Strip whitespace and separators, fold Persian/Arabic digits to ASCII."""
    if not raw:
        return ""
    folded = raw.translate(_TRANSLATION)
    return re.sub(r"[\s,٬،_-]", "", folded).strip()


def is_valid_bitunix_uid(candidate: str) -> bool:
    return bool(BITUNIX_UID_PATTERN.match(candidate))
