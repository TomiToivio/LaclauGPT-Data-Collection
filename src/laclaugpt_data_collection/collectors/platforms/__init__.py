"""LaclauGPT-native platform parser registry."""

from . import instagram, tiktok, tiktok_extras, twitter

PARSERS = {
    "tiktok": tiktok,
    "instagram": instagram,
    "x": twitter,
    "twitter": twitter,
}

# Auxiliary record families (legacy salvage): comment/user/challenge objects
# use distinct platform-kind values so dedup keys never collide with posts.
AUX_PARSERS = {
    "tiktok_comment": tiktok_extras,
    "tiktok_user": tiktok_extras,
    "tiktok_challenge": tiktok_extras,
}

__all__ = ["PARSERS", "AUX_PARSERS", "instagram", "tiktok", "tiktok_extras", "twitter"]