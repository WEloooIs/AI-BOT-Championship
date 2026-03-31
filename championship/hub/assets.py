from __future__ import annotations

from pathlib import Path

import tkinter as tk
from PIL import Image, ImageDraw, ImageOps, ImageTk


_PHOTO_CACHE: dict[tuple[str, tuple[int, int]], ImageTk.PhotoImage] = {}


def _placeholder(size: tuple[int, int], label: str = "?") -> Image.Image:
    image = Image.new("RGBA", size, "#202228")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=14, outline="#31333a", width=2, fill="#202228")
    draw.text((size[0] // 2, size[1] // 2), label[:2].upper(), fill="#f5efe8", anchor="mm")
    return image


def load_tk_image(path: Path | None, size: tuple[int, int], *, fallback_label: str = "?") -> ImageTk.PhotoImage:
    cache_key = (str(path) if path else "", size)
    cached = _PHOTO_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if path and path.exists():
        image = Image.open(path).convert("RGBA")
        image = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
        background = Image.new("RGBA", size, "#202228")
        offset = ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
        background.alpha_composite(image, dest=offset)
        image = background
    else:
        image = _placeholder(size, fallback_label)

    photo = ImageTk.PhotoImage(image)
    _PHOTO_CACHE[cache_key] = photo
    return photo


def clear_image_cache() -> None:
    _PHOTO_CACHE.clear()
