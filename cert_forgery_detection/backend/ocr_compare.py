"""
ocr_compare.py
Unified field-level tamper detection for both 10th (SSLC) and 12th (HSC).

10th (SSLC): Robust multi-method extraction (deskew, multi-variant enhance,
             multi-PSM Tesseract, EasyOCR ROI fallback, flattened-text retry)
12th (HSC):  EasyOCR + pytesseract ROI (UNCHANGED from previous version)
"""

import os
import re
import cv2
import requests
import numpy as np
import pytesseract
from bs4 import BeautifulSoup

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

DEBUG = True

# EasyOCR lazy loaded — shared by both 10th and 12th paths
_reader    = None
_reader_ok = False

def _get_reader():
    global _reader, _reader_ok
    if _reader is None:
        try:
            import easyocr
            _reader    = easyocr.Reader(['en'], gpu=False, verbose=False)
            _reader_ok = True
        except Exception:
            _reader_ok = False
    return _reader, _reader_ok


# ══════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ══════════════════════════════════════════════════════════════════════════

def _load_image(file_path: str) -> np.ndarray:
    """Load image or convert first page of PDF to BGR image (dpi=200, shared loader)."""
    if file_path.lower().endswith(".pdf"):
        from pdf2image import convert_from_path
        pages = convert_from_path(file_path, dpi=200)
        img   = np.array(pages[0])
        img   = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        img = cv2.imread(file_path)
    if img is None:
        raise ValueError(f"Cannot load file: {file_path}")
    return img


def _load_image_highres(file_path: str) -> np.ndarray:
    """Higher-res loader (dpi=300) used by the new 10th register-number logic,
    matching the resolution the new code was designed and tuned against."""
    if file_path.lower().endswith(".pdf"):
        from pdf2image import convert_from_path
        pages = convert_from_path(file_path, dpi=300)
        img   = np.array(pages[0])
        img   = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return img
    return cv2.imread(file_path)


def _normalize_digits(text: str) -> str:
    text = str(text).upper()
    for k, v in {"O":"0","I":"1","L":"1","S":"5","B":"8"}.items():
        text = text.replace(k, v)
    return text


# ══════════════════════════════════════════════════════════════════════════
# DIGITAL SOURCE — download from QR URL
# ══════════════════════════════════════════════════════════════════════════

def _download_source(url: str) -> str:
    """
    Try multiple header strategies to fetch the TN DGE certificate page.
    Returns plain uppercase text or raises exception.
    """
    headers_list = [
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        },
        {"User-Agent": "Mozilla/5.0"},
        {},
    ]

    last_error = None
    for headers in headers_list:
        try:
            session = requests.Session()
            try:
                session.get("https://certverify.tndge.org", timeout=8, headers=headers)
            except Exception:
                pass
            r = session.get(url, headers=headers, timeout=15, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 100:
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style"]):
                    tag.extract()
                text = soup.get_text(" ", strip=True).upper()
                if len(text) > 50:
                    return text
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Could not fetch certificate page. Last error: {last_error}")


# ══════════════════════════════════════════════════════════════════════════
# 10th (SSLC) — NEW ROBUST LOGIC (integrated as-is from the provided code)
# ══════════════════════════════════════════════════════════════════════════

def normalize_regno(text):
    """
    FIX 1: Added 'A' -> '4' mapping.
    OCR frequently reads the digit '4' as 'A' (especially in ALL-CAPS scans).
    Applied only to the numeric zones of the register number by running a
    targeted substitution after the two-letter prefix 'XM'.
    """
    text = text.upper()
    mapping = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"}
    for k, v in mapping.items():
        text = text.replace(k, v)

    def fix_xm_digits(m):
        token = m.group(0)
        chars = list(token)
        for idx in [2, 3]:
            if idx < len(chars) and chars[idx] == 'A':
                chars[idx] = '4'
        return "".join(chars)

    text = re.sub(r'XM[A-Z0-9]{10,20}', fix_xm_digits, text)
    return text


def clean_ocr_text(text):
    text = text.upper()
    text = text.replace(" ", "")
    text = text.replace("\n", "")
    text = text.replace("I", "1")
    text = text.replace("O", "0")
    text = text.replace("L", "1")
    return text


def extract_regno(text):
    """Digital-copy register number extraction for 10th (SSLC)."""
    text = normalize_regno(text.upper())
    text = re.sub(r'\s+', '', text)

    patterns = [
        r'PERMANENTREGISTERNUMBER[:\-]?(XM\d{2}[A-Z]\d{6,15})',
        r'REGISTERNUMBER[:\-]?(\d{6,12})',
        r'(XM\d{2}[A-Z]\d{6,15})',
        r'\b(\d{6,12})\b',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return "NOT FOUND"


def extract_marks(text):
    """Digital-copy total marks extraction for 10th (SSLC)."""
    text = text.upper()
    patterns = [
        r'TOTAL\s+MARKS\s*[:\-]?\s*(\d{3,4})',
        r'GRAND\s+TOTAL\s*[:\-]?\s*(\d{3,4})',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).zfill(4)

    blocks = text.split()
    for i, w in enumerate(blocks):
        if "TOTAL" in w:
            window = " ".join(blocks[i:i+8])
            nums   = re.findall(r'\b\d{3,4}\b', window)
            valid  = [int(n) for n in nums if 300 <= int(n) <= 1200]
            if valid:
                return str(min(valid)).zfill(4)
    return "NOT FOUND"


def deskew(gray):
    """Corrects small rotation skew (0.5°-15°) in a grayscale ROI."""
    thresh = cv2.threshold(gray, 0, 255,
                            cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] < 20:
        return gray

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    if abs(angle) < 0.5 or abs(angle) > 15:
        return gray

    h, w = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h),
                           flags=cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_REPLICATE)


def enhance_variants(gray):
    """Produces several independently preprocessed versions of the same ROI."""
    variants = []

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    eq    = clahe.apply(gray)
    _, otsu = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    variants.append(otsu)

    denoised = cv2.fastNlMeansDenoising(gray, h=10)
    adaptive = cv2.adaptiveThreshold(denoised, 255,
                                      cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                      cv2.THRESH_BINARY, 31, 11)
    variants.append(adaptive)

    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharp  = cv2.filter2D(gray, -1, kernel)
    _, sharp_otsu = cv2.threshold(sharp, 0, 255,
                                   cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    variants.append(sharp_otsu)

    variants.append(gray)
    return variants


def _regno_crop(img, cert_type, upscale):
    """Shared ROI crop + upscale used by both Tesseract and EasyOCR fallbacks."""
    h, w = img.shape[:2]
    if cert_type == "SSLC":
        roi = img[int(h*0.55):int(h*0.98), int(w*0.40):int(w*0.98)]
    else:
        roi = img[int(h*0.20):int(h*0.75), int(w*0.40):int(w*0.98)]
    return cv2.resize(roi, None, fx=upscale, fy=upscale,
                       interpolation=cv2.INTER_CUBIC)


def _match_regno_pattern(txt, cert_type):
    m = re.search(r'XM\d{2}[A-Z]\d{7,12}', txt)
    if m:
        return m.group()

    flattened = re.sub(r'\s+', '', txt)
    m = re.search(r'XM\d{2}[A-Z]\d{7,12}', flattened)
    if m:
        return m.group()

    cleaned = re.sub(r'[^0-9\s]', ' ', txt)
    if cert_type == "SSLC":
        nums = re.findall(r'\b\d{7}\b', cleaned)
    else:
        nums = re.findall(r'\b2\d{9}\b', cleaned)
    return nums[0] if nums else None


def extract_regno_roi(image_path, cert_type, upscale=6):
    """Tesseract on a deskewed, multi-variant-enhanced, multi-PSM crop."""
    img = _load_image_highres(image_path)
    if img is None:
        return "NOT FOUND"

    roi  = _regno_crop(img, cert_type, upscale)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = deskew(gray)

    for variant in enhance_variants(gray):
        for psm in (6, 7, 11, 13):
            txt = pytesseract.image_to_string(
                variant, config=f"--oem 3 --psm {psm}").upper()
            match = _match_regno_pattern(txt, cert_type)
            if match:
                return match
    return "NOT FOUND"


def extract_regno_easyocr_roi(image_path, cert_type, upscale=4):
    """Second independent OCR pass (EasyOCR) on the same cropped region."""
    reader, ok = _get_reader()
    if not ok:
        return "NOT FOUND"

    img = _load_image_highres(image_path)
    if img is None:
        return "NOT FOUND"

    roi     = _regno_crop(img, cert_type, upscale)
    results = reader.readtext(roi)
    txt     = normalize_regno(" ".join(t.upper() for (_, t, _) in results))

    match = _match_regno_pattern(txt, cert_type)
    return match if match else "NOT FOUND"


def extract_regno_from_ocr(ocr_text):
    """Full-page OCR text register number extraction (with flattened retry)."""
    ocr_text = normalize_regno(ocr_text)

    m = re.search(r'XM\d{2}[A-Z]\d{7,12}', ocr_text)
    if m:
        return m.group()

    flattened = ocr_text.replace("\n", "")
    m = re.search(r'XM\d{2}[A-Z]\d{7,12}', flattened)
    if m:
        return m.group()

    m = re.search(r'ROLL\s*NO[.\s]*(\d{6,8})', ocr_text, re.I | re.S)
    if m:
        return m.group(1)

    m = re.search(r'\b(\d{7})\b', ocr_text)
    if m:
        return m.group(1)

    return "NOT FOUND"


def get_full_ocr_text_10th(image_path):
    """Full-page EasyOCR text used as the first-chance register number method."""
    reader, ok = _get_reader()
    if not ok:
        return ""
    img = _load_image_highres(image_path)
    if img is None:
        return ""
    results  = reader.readtext(img)
    lines    = [text.upper() for (bbox, text, conf) in results]
    return "\n".join(lines)


def resolve_scanned_regno(image_path, ocr_text, cert_type):
    """
    Chains independent register-number extraction strategies and returns
    the first one that succeeds:
      1. full-page EasyOCR text (already collected, free)
      2. Tesseract on deskewed/enhanced ROI, multiple PSM modes
      3. EasyOCR on the same cropped ROI
    """
    methods = [
        ("full-page EasyOCR", lambda: extract_regno_from_ocr(ocr_text)),
        ("Tesseract ROI",      lambda: extract_regno_roi(image_path, cert_type)),
        ("EasyOCR ROI",        lambda: extract_regno_easyocr_roi(image_path, cert_type)),
    ]
    for name, fn in methods:
        result = fn()
        if result != "NOT FOUND":
            if DEBUG:
                print(f"[DEBUG] 10th register number resolved via: {name}")
            return result
    return "NOT FOUND"


def extract_total_marks_from_ocr(ocr_text):
    """
    Total marks extraction for 10th. Looks only at text AFTER the TOTAL
    keyword within a 3-line window, skipping any numeric noise before it.
    """
    lines = ocr_text.split("\n")
    KEYWORDS = ["TOTAL MARKS", "GRAND TOTAL"]

    for i, line in enumerate(lines):
        matched_kw = None
        for kw in KEYWORDS:
            if kw in line:
                matched_kw = kw
                break
        if matched_kw is None:
            continue

        window = "\n".join(lines[i: i + 3])
        kw_pos = window.find(matched_kw)
        suffix = window[kw_pos + len(matched_kw):]

        suffix_clean = re.sub(r'[^0-9\s]', ' ', suffix)
        nums = re.findall(r'\b\d{3,4}\b', suffix_clean)

        for n in nums:
            val = int(n)
            if 100 <= val <= 1200:
                return str(val).zfill(4)

    return "NOT FOUND"


def detect_certificate_type(text):
    text = text.upper()
    if "SSLC" in text:
        return "SSLC"
    elif "HSC" in text:
        return "HSC"
    return "UNKNOWN"


def _is_corona_batch(text: str) -> bool:
    return bool(re.search(r'MAR\s*2021', text, re.I))


def _process_10th(file_path: str, qr_url: str) -> dict:
    """
    Full 10th (SSLC) pipeline using the new robust extraction logic.
    Mirrors process_certificate() from the provided code, adapted to
    return a structured result instead of printing/saving CSV.
    """
    fetch_error = None
    try:
        digital_text = _download_source(qr_url)
        cert_type_detected = detect_certificate_type(digital_text)
        digital_reg   = extract_regno(clean_ocr_text(digital_text))
        digital_marks = extract_marks(digital_text)
        if _is_corona_batch(digital_text):
            if re.search(r'\bPASS\b', digital_text, re.I):
                digital_marks = "PASS"
            elif re.search(r'\bFAIL\b', digital_text, re.I):
                digital_marks = "FAIL"
    except Exception as e:
        fetch_error   = str(e)
        digital_reg   = "FETCH ERROR"
        digital_marks = "FETCH ERROR"
        cert_type_detected = "SSLC"

    ocr_text      = get_full_ocr_text_10th(file_path)
    scanned_reg   = resolve_scanned_regno(file_path, ocr_text, cert_type_detected)
    scanned_marks = extract_total_marks_from_ocr(ocr_text)

    if scanned_marks == "NOT FOUND" and _is_corona_batch(ocr_text):
        if re.search(r'\bPASS\b', ocr_text):
            scanned_marks = "PASS"
        elif re.search(r'\bFAIL\b', ocr_text):
            scanned_marks = "FAIL"

    return {
        "digital_reg":   digital_reg,
        "digital_marks": digital_marks,
        "scanned_reg":   scanned_reg,
        "scanned_marks": scanned_marks,
        "fetch_error":   fetch_error,
    }


# ══════════════════════════════════════════════════════════════════════════
# 12th (HSC) — UNCHANGED FROM PREVIOUS VERSION
# ══════════════════════════════════════════════════════════════════════════

def _extract_digital_regno_12th(text: str) -> str:
    patterns = [
        r'PERMANENT\s+REGISTER\s+NUMBER\s*[:\-]?\s*(\d{10,12})',
        r'PERMANENT\s+REGISTER\s+NO[:\-]?\s*(\d{10,12})',
        r'REGISTER\s+NUMBER\s*[:\-]?\s*(\d{10,12})',
        r'\b(XM\d{2}[A-Z]\d{7,12})\b',
        r'\b(2\d{9,11})\b',
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return _normalize_digits(m.group(1))
    return "NOT FOUND"


def _extract_digital_marks_12th(text: str) -> str:
    patterns = [
        r'TOTAL\s+MARKS\s*[:\-]?\s*(\d{3,4})',
        r'GRAND\s+TOTAL\s*[:\-]?\s*(\d{3,4})',
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1).zfill(4)
    return "NOT FOUND"


def _extract_scanned_regno_12th(img: np.ndarray) -> str:
    reader, ok = _get_reader()
    if not ok:
        return _fallback_regno_pytesseract_12th(img)

    results  = reader.readtext(img)
    all_text = [(t.upper(), int(min(p[1] for p in bbox)))
                for bbox, t, _ in results]

    for i, (txt, _) in enumerate(all_text):
        if "REGISTER" in txt or "PERMANENT" in txt:
            block = " ".join(all_text[j][0]
                             for j in range(max(0,i-2), min(len(all_text),i+8)))
            nums  = re.findall(r'\b\d{10}\b', block)
            if nums:
                preferred = [n for n in nums if n.startswith("22")]
                return preferred[0] if preferred else nums[0]

    full = " ".join(x[0] for x in all_text)
    m    = re.search(r'\b(XM\d{2}[A-Z]\d{7,12})\b', full)
    if m:
        return m.group(1)
    nums = re.findall(r'\b\d{10}\b', full)
    for n in nums:
        if n.startswith("22"):
            return n
    return nums[0] if nums else "NOT FOUND"


def _extract_scanned_marks_12th(img: np.ndarray) -> str:
    reader, ok = _get_reader()
    if not ok:
        return _fallback_marks_pytesseract_12th(img)

    results    = reader.readtext(img)
    candidates = []
    for bbox, text, _ in results:
        if any(k in text.upper() for k in ["TOTAL","GRAND TOTAL","MARKS"]):
            x1  = int(min(p[0] for p in bbox))
            y1  = int(min(p[1] for p in bbox))
            x2  = int(max(p[0] for p in bbox))
            y2  = int(max(p[1] for p in bbox))
            roi = img[max(0,y1-50):min(img.shape[0],y2+250),
                      max(0,x1-50):min(img.shape[1],x2+400)]
            txt = pytesseract.image_to_string(roi, config='--oem 3 --psm 6')
            for n in re.findall(r'\b\d{3,4}\b', txt):
                v = int(n)
                if v in range(1990,2100):
                    continue
                if 300 <= v <= 1200:
                    candidates.append(n)

    if candidates:
        return max(candidates, key=lambda x: int(x)).zfill(4)
    return _fallback_marks_pytesseract_12th(img)


def _fallback_regno_pytesseract_12th(img: np.ndarray) -> str:
    txt  = pytesseract.image_to_string(img, config='--oem 3 --psm 6').upper()
    txt  = normalize_regno(txt)
    m    = re.search(r'\b(XM\d{2}[A-Z]\d{7,12})\b', txt)
    if m:
        return m.group(1)
    nums = re.findall(r'\b\d{10}\b', txt)
    for n in nums:
        if n.startswith("22"):
            return n
    return nums[0] if nums else "NOT FOUND"


def _fallback_marks_pytesseract_12th(img: np.ndarray) -> str:
    txt   = pytesseract.image_to_string(img, config='--oem 3 --psm 6').upper()
    m     = re.search(r'TOTAL\s+MARKS\s*[:\-]?\s*(\d{3,4})', txt)
    if m:
        return m.group(1).zfill(4)
    nums  = re.findall(r'\b\d{3,4}\b', txt)
    cands = [n for n in nums
             if 300 <= int(n) <= 1200 and int(n) not in range(1990,2100)]
    return max(cands, key=lambda x: int(x)).zfill(4) if cands else "NOT FOUND"


def _process_12th(file_path: str, qr_url: str) -> dict:
    """12th (HSC) pipeline — unchanged logic from previous version."""
    fetch_error = None
    try:
        digital_text  = _download_source(qr_url)
        digital_regno = _extract_digital_regno_12th(digital_text)
        digital_marks = _extract_digital_marks_12th(digital_text)
    except Exception as e:
        fetch_error   = str(e)
        digital_regno = "FETCH ERROR"
        digital_marks = "FETCH ERROR"

    img           = _load_image(file_path)
    scanned_regno = _extract_scanned_regno_12th(img)
    scanned_marks = _extract_scanned_marks_12th(img)

    return {
        "digital_reg":   digital_regno,
        "digital_marks": digital_marks,
        "scanned_reg":   scanned_regno,
        "scanned_marks": scanned_marks,
        "fetch_error":   fetch_error,
    }


# ══════════════════════════════════════════════════════════════════════════
# STATUS HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _regno_status(digital: str, scanned: str) -> str:
    if digital in ("NOT FOUND","FETCH ERROR") or scanned == "NOT FOUND":
        return "UNDETECTED"
    if normalize_regno(digital) == normalize_regno(scanned):
        return "MATCH"
    return "TAMPERED"


def _marks_status(digital: str, scanned: str) -> str:
    if digital in ("NOT FOUND","FETCH ERROR") or scanned == "NOT FOUND":
        return "UNDETECTED"
    if digital in ("PASS","FAIL"):
        if scanned in ("PASS","FAIL"):
            return "MATCH"
        return "TAMPERED"
    if digital == scanned:
        return "MATCH"
    return "TAMPERED"


# ══════════════════════════════════════════════════════════════════════════
# MAIN — called from app.py
# ══════════════════════════════════════════════════════════════════════════

def compare_fields(file_path: str, qr_url: str, cert_type: str = "10") -> dict:
    """
    cert_type: "10" → SSLC, uses the new robust multi-method extraction
               "12" → HSC,  uses the existing EasyOCR + pytesseract logic
    """
    if cert_type == "10":
        data = _process_10th(file_path, qr_url)
    else:
        data = _process_12th(file_path, qr_url)

    digital_reg, digital_marks = data["digital_reg"], data["digital_marks"]
    scanned_reg, scanned_marks = data["scanned_reg"], data["scanned_marks"]

    regno_s = _regno_status(digital_reg, scanned_reg)
    marks_s = _marks_status(digital_marks, scanned_marks)

    statuses = [regno_s, marks_s]
    if "TAMPERED" in statuses:
        verdict = "TAMPERED"
    elif all(s == "MATCH" for s in statuses):
        verdict = "GENUINE"
    else:
        verdict = "UNVERIFIED"

    _, ok = _get_reader()

    result = {
        "verdict": verdict,
        "fields": [
            {
                "field":   "Register Number",
                "digital": digital_reg,
                "scanned": scanned_reg,
                "status":  regno_s,
            },
            {
                "field":   "Total Marks",
                "digital": digital_marks,
                "scanned": scanned_marks,
                "status":  marks_s,
            },
        ],
        "easyocr_used": ok,
    }

    if data.get("fetch_error"):
        result["fetch_error"] = data["fetch_error"]

    return result