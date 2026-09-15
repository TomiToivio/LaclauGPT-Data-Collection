"""LaclauGPT-native platform parser registry."""

from . import instagram, tiktok, twitter

PARSERS = {
    "tiktok": tiktok,
    "instagram": instagram,
    "x": twitter,
    "twitter": twitter,
}

__all__ = ["PARSERS", "instagram", "tiktok", "twitter"]
