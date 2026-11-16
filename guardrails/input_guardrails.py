"""
guardrails/input_guardrails.py
==============================
Validates ALL user-supplied inputs before they reach the LLM agents.

Checks implemented:
  IMAGE
    1. MIME type allowlist (JPEG / PNG / WEBP)
    2. File size ≤ 10 MB
    3. Image dimensions — minimum 50×50 px, maximum 8000×8000 px
    4. Minimum file size > 1 KB (empty / corrupt file guard)

  TEXT
    5.  Character-length limit (≤ 500 chars)
    6.  Prompt-injection pattern detection (20 patterns)
    7.  Unicode homoglyph / obfuscation detection
    8.  PII detection — email, phone number, national-ID patterns
    9.  Null-byte / binary content guard
    10. Repeated-character flooding guard

Public API:
  check_image(uploaded_file) -> GuardrailResult
  check_text(text)           -> GuardrailResult
  check_pii(text)            -> GuardrailResult
"""

import re
import io
from guardrails import GuardrailResult, GuardrailSeverity

# ── Image constants ────────────────────────────────────────────────────────────
ALLOWED_MIME_TYPES  = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024    # 10 MB
MIN_FILE_SIZE_BYTES = 1024                # 1 KB  — guard against empty uploads
MIN_IMAGE_DIM       = 50                  # pixels (width or height)
MAX_IMAGE_DIM       = 8000               # pixels

# ── Text constants ─────────────────────────────────────────────────────────────
MAX_NOTE_CHARS      = 500
MAX_REPEATED_CHARS  = 30   # e.g. "aaaaaaaaa..." is suspicious


# ── Prompt-injection patterns ──────────────────────────────────────────────────
# Covers direct instructions, role-switching, goal hijacking, encoding tricks
_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above|prior)\s+instructions?",
    r"disregard\s+(all|previous|prior)",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(if\s+you\s+are|a\s+different)",
    r"jailbreak",
    r"<\s*script",
    r"system\s*prompt",
    r"bypass\s+(safety|filter|guardrail|restriction)",
    r"forget\s+(all|previous)\s+(instruction|rule|constraint)",
    r"reveal\s+(your|the)\s+(system\s+)?prompt",
    r"new\s+instructions?\s*:",
    r"override\s+(your|all)\s+(instruction|setting|rule)",
    r"do\s+not\s+follow\s+(the\s+)?(previous|original|prior)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"role\s*play\s+as",
    r"dan\s+mode",                 # "Do Anything Now" jailbreak
    r"developer\s+mode",
    r"sudo\s+",                    # Unix privilege escalation metaphor
    r"prompt\s*injection",
    r"escape\s+(the\s+)?(sandbox|restriction|filter)",
]
_INJECTION_RE = re.compile(
    "|".join(_INJECTION_PATTERNS),
    flags=re.IGNORECASE | re.DOTALL,
)

# ── PII patterns ───────────────────────────────────────────────────────────────
# Detect personal information that should not be sent to the LLM
_PII_PATTERNS = {
    "email":       re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "phone_intl":  re.compile(r"\+?\d[\d\s\-().]{7,14}\d"),
    "credit_card": re.compile(r"\b(?:\d[ \-]?){13,16}\b"),
    "ssn_us":      re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"),
    "passport":    re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),
    "aadhaar":     re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),   # Indian national ID
}

# ── Unicode homoglyph detection ───────────────────────────────────────────────
# Characters from non-Latin scripts that visually resemble ASCII letters
# Used to bypass keyword filters (e.g. Cyrillic "а" looks like Latin "a")
_HOMOGLYPH_RE = re.compile(
    r"[\u0400-\u04FF"   # Cyrillic
    r"\u0370-\u03FF"   # Greek
    r"\u2100-\u214F"   # Letterlike symbols
    r"\uFF01-\uFF5E]"  # Fullwidth ASCII variants
)


# ── Public API ────────────────────────────────────────────────────────────────

def check_image(uploaded_file) -> GuardrailResult:
    """
    Validate an uploaded crop image.

    Checks: MIME type, file size bounds, image dimensions.

    Returns:
        GuardrailResult with layer="input_image"
    """
    layer = "input_image"

    # 1. MIME type
    mime = getattr(uploaded_file, "type", "")
    if mime not in ALLOWED_MIME_TYPES:
        return GuardrailResult(
            passed=False,
            reason=f"File type '{mime}' is not allowed. Upload a JPEG, PNG, or WEBP image.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    # 2. Read bytes (without consuming the stream permanently)
    try:
        raw = uploaded_file.read()
        uploaded_file.seek(0)
        size = len(raw)
    except Exception as exc:
        return GuardrailResult(
            passed=False,
            reason=f"Could not read uploaded file: {exc}",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    # 3. Minimum file size (guard against empty / corrupt uploads)
    if size < MIN_FILE_SIZE_BYTES:
        return GuardrailResult(
            passed=False,
            reason=f"Image file is too small ({size} bytes). Minimum is {MIN_FILE_SIZE_BYTES} bytes. "
                   "The file may be empty or corrupt.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"file_size_bytes": size},
        )

    # 4. Maximum file size
    if size > MAX_FILE_SIZE_BYTES:
        mb = size / (1024 * 1024)
        return GuardrailResult(
            passed=False,
            reason=f"Image size {mb:.1f} MB exceeds the 10 MB limit. Please resize the image.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"file_size_bytes": size},
        )

    # 5. Image dimensions — requires Pillow, fail open if unavailable
    try:
        from PIL import Image as _PILImage
        img = _PILImage.open(io.BytesIO(raw))
        w, h = img.size
        uploaded_file.seek(0)

        if w < MIN_IMAGE_DIM or h < MIN_IMAGE_DIM:
            return GuardrailResult(
                passed=False,
                reason=f"Image is too small ({w}×{h} px). Minimum size is {MIN_IMAGE_DIM}×{MIN_IMAGE_DIM} px. "
                       "Upload a clear, full-resolution crop photo.",
                layer=layer,
                severity=GuardrailSeverity.BLOCK,
                details={"width": w, "height": h},
            )

        if w > MAX_IMAGE_DIM or h > MAX_IMAGE_DIM:
            # Warn but do not block — image_utils will resize it
            return GuardrailResult(
                passed=True,
                reason=f"Image is very large ({w}×{h} px) and will be automatically resized for analysis.",
                layer=layer,
                severity=GuardrailSeverity.WARNING,
                details={"width": w, "height": h},
            )
    except Exception:
        # Dimension check failed — still allow; image_utils will catch corrupt files
        uploaded_file.seek(0)

    return GuardrailResult(
        passed=True,
        reason="Image passed all checks.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )


def check_text(text: str) -> GuardrailResult:
    """
    Validate a user-supplied text note.

    Checks: length, prompt injection, homoglyph obfuscation,
            null bytes / binary content, character flooding.

    Returns:
        GuardrailResult with layer="input_text"
    """
    layer = "input_text"

    if not text:
        return GuardrailResult(passed=True, reason="Empty text — no checks needed.", layer=layer)

    # 1. Length limit
    if len(text) > MAX_NOTE_CHARS:
        return GuardrailResult(
            passed=False,
            reason=f"Note is {len(text)} characters; maximum allowed is {MAX_NOTE_CHARS}.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"char_count": len(text), "limit": MAX_NOTE_CHARS},
        )

    # 2. Null bytes / binary content
    if "\x00" in text or any(ord(c) < 9 for c in text):
        return GuardrailResult(
            passed=False,
            reason="Input contains null bytes or binary control characters.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    # 3. Prompt injection
    match = _INJECTION_RE.search(text)
    if match:
        return GuardrailResult(
            passed=False,
            reason="Input contains a prompt injection pattern and was blocked.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"matched_text": text[max(0, match.start()-10):match.end()+10]},
        )

    # 4. Unicode homoglyph obfuscation
    if _HOMOGLYPH_RE.search(text):
        return GuardrailResult(
            passed=False,
            reason="Input contains non-Latin Unicode characters that may be used to obfuscate injection attempts.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    # 5. Repeated-character flooding (e.g. "aaaaaaaaaa...")
    # (.)\1{N,} matches the char + N more of the same = N+1 total.
    # Block when total run >= MAX_REPEATED_CHARS+1, so N = MAX_REPEATED_CHARS-1.
    if re.search(r"(.)\1{" + str(MAX_REPEATED_CHARS - 1) + r",}", text):
        return GuardrailResult(
            passed=False,
            reason=f"Input contains a suspicious run of repeated characters (> {MAX_REPEATED_CHARS} consecutive).",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    return GuardrailResult(
        passed=True,
        reason="Text passed all checks.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )


def check_pii(text: str) -> GuardrailResult:
    """
    Detect personally identifiable information (PII) in user-supplied text.

    PII types checked: email, international phone, credit card,
    US SSN, passport number, Indian Aadhaar number.

    Returns:
        GuardrailResult with layer="input_pii"
        passed=False if PII is detected (block from reaching the LLM).
        Details include the PII types found (but NOT the actual values).
    """
    layer = "input_pii"

    if not text:
        return GuardrailResult(passed=True, reason="Empty text.", layer=layer)

    found_types = []
    for pii_type, pattern in _PII_PATTERNS.items():
        if pattern.search(text):
            found_types.append(pii_type)

    if found_types:
        return GuardrailResult(
            passed=False,
            reason=(
                f"Input appears to contain personal information ({', '.join(found_types)}). "
                "Please remove personal details before submitting — the farm note should "
                "describe crop symptoms only."
            ),
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"pii_types": found_types},
        )

    return GuardrailResult(
        passed=True,
        reason="No PII detected.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )
