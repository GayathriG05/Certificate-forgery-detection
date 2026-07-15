"""
qr_check.py  —  Detect QR codes in scanned certificate PDFs / images
                and validate the embedded URL against TN DGE official domain.
"""

import re
import cv2
import numpy as np
from urllib.parse import urlparse


def _rotate(img, angle):
    h, w   = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(img, matrix, (w, h))


def _preprocess_versions(img):
    versions = []
    gray     = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    versions.append(gray)
    clahe    = cv2.createCLAHE(2.0, (8, 8))
    contrast = clahe.apply(gray)
    versions.append(contrast)
    kernel   = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharp    = cv2.filter2D(contrast, -1, kernel)
    versions.append(sharp)
    adaptive = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    versions.append(adaptive)
    return versions


def _detect_qr_from_image(img) -> str | None:
    """Try multiple pre-processing passes and rotations to find a QR code."""
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        pyzbar_available = True
    except ImportError:
        pyzbar_available = False

    img    = cv2.resize(img, None, fx=3, fy=3)
    qr_det = cv2.QRCodeDetector()

    for v in _preprocess_versions(img):
        for angle in [0, 90, 180, 270]:
            rotated = _rotate(v, angle)
            # Try OpenCV
            data, _, _ = qr_det.detectAndDecode(rotated)
            if data:
                return data
            # Try pyzbar
            if pyzbar_available:
                decoded = pyzbar_decode(rotated)
                if decoded:
                    return decoded[0].data.decode("utf-8")
    return None


def detect_qr_from_file(file_path: str) -> str | None:
    """
    Accept a PDF or image file, convert first page if PDF,
    then scan for a QR code. Returns the decoded string or None.
    """
    path_lower = file_path.lower()

    if path_lower.endswith(".pdf"):
        from pdf2image import convert_from_path
        pages = convert_from_path(file_path, dpi=150)
        img   = np.array(pages[0])
        img   = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        img = cv2.imread(file_path)

    if img is None:
        raise ValueError(f"Cannot load file: {file_path}")

    return _detect_qr_from_image(img)


def check_official_url(url: str) -> tuple[bool, bool]:
    """
    Returns (domain_ok, path_ok).
    Official TN DGE certificates point to certverify.tndge.org
    with a path matching /ceti-verify/<token>[/<token>...]
    """
    try:
        parsed    = urlparse(url)
        domain    = parsed.netloc.lower()
        path      = parsed.path.lower()
        domain_ok = (domain == "certverify.tndge.org")
        pattern   = r"^/ceti-verify/[a-z0-9]+(/[a-z0-9]+)*$"
        path_ok   = bool(re.match(pattern, path))
        return domain_ok, path_ok
    except Exception:
        return False, False