"""
utils/image_utils.py
====================
Image loading, validation, resizing, and base64 encoding for Agri Doctor.

Functions:
  - load_and_validate_image(uploaded_file) → PIL.Image.Image
  - resize_for_model(pil_image, max_px)    → PIL.Image.Image
  - encode_image_base64(pil_image)         → str
"""

import io
import base64
from PIL import Image

# ── Constants ─────────────────────────────────────────────────────────────────
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_MODEL_PIXELS    = 1024               # longest edge in pixels


# ── Public API ────────────────────────────────────────────────────────────────

def load_and_validate_image(uploaded_file) -> Image.Image:
    """
    Load a Streamlit UploadedFile as a PIL Image after validating MIME type
    and file size.

    Args:
        uploaded_file: Streamlit UploadedFile object.

    Returns:
        PIL.Image.Image (RGB mode)

    Raises:
        ValueError: If the file type is not allowed or size exceeds limit.
    """
    # MIME type check
    mime = getattr(uploaded_file, "type", "")
    if mime not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"Unsupported file type '{mime}'. "
            f"Please upload a JPEG, PNG, or WEBP image."
        )

    # Read bytes
    raw_bytes = uploaded_file.read()

    # Size check
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        size_mb = len(raw_bytes) / (1024 * 1024)
        raise ValueError(
            f"Image size {size_mb:.1f} MB exceeds the 10 MB limit. "
            f"Please upload a smaller image."
        )

    # Open with Pillow
    try:
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Could not open image: {exc}") from exc

    # Reset file pointer for any downstream readers
    uploaded_file.seek(0)
    return img


def resize_for_model(pil_image: Image.Image, max_px: int = MAX_MODEL_PIXELS) -> Image.Image:
    """
    Resize a PIL image so its longest edge does not exceed max_px pixels.
    Preserves aspect ratio. Returns the original if already small enough.

    Args:
        pil_image: PIL Image in RGB mode.
        max_px: Maximum allowed size for the longest edge (default 1024).

    Returns:
        Resized PIL.Image.Image
    """
    w, h = pil_image.size
    longest = max(w, h)
    if longest <= max_px:
        return pil_image

    scale = max_px / longest
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return pil_image.resize((new_w, new_h), Image.LANCZOS)


def encode_image_base64(pil_image: Image.Image) -> str:
    """
    Encode a PIL Image as a base64 JPEG string (no data URI prefix).
    The image is first resized to fit within MAX_MODEL_PIXELS.

    Args:
        pil_image: PIL Image in RGB mode.

    Returns:
        Base64-encoded JPEG string.
    """
    img = resize_for_model(pil_image)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85, optimize=True)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")
