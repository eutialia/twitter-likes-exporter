"""Syndication widget constants and token derivation. httpx-free."""

from __future__ import annotations

import math
import re

SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def make_syndication_token(tweet_id: str | int) -> str:
    """Replicate the widget JS: ((id / 1e15) * Math.PI).toString(36).replace(/(0+|\\.)/g, '')."""
    n = (int(tweet_id) / 1e15) * math.pi
    int_part = int(n)
    frac = n - int_part

    s_int = "0" if int_part == 0 else ""
    tmp = int_part
    while tmp > 0:
        s_int = _BASE36[tmp % 36] + s_int
        tmp //= 36

    s_frac = ""
    for _ in range(20):
        if frac == 0:
            break
        frac *= 36
        d = int(frac)
        s_frac += _BASE36[d]
        frac -= d

    s = s_int + (("." + s_frac) if s_frac else "")
    return re.sub(r"(0+|\.)", "", s)
