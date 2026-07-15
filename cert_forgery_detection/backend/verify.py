"""
verify.py — Extract fields from submitted certificate and compare hash against blockchain.
- Faster: cached web3 connection, reduced redundant operations
- Better register number extraction using robust multi-pattern approach
- No duplicate detect_pdf_type / ocr_extract functions
"""

import re
import json
import hashlib
import logging
import warnings
import os
from typing import Optional

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

try:
    from web3 import Web3
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False

warnings.filterwarnings("ignore")
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# ── Blockchain config ──────────────────────────────────────────────────────
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
RPC_URL          = os.getenv("RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
CHAIN_ID         = int(os.getenv("CHAIN_ID", "11155111"))

ABI = json.loads('[{"inputs":[{"internalType":"string","name":"regNo","type":"string"},{"internalType":"string","name":"certType","type":"string"},{"internalType":"string","name":"compositeHash","type":"string"}],"name":"storeCertificate","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"string","name":"regNo","type":"string"},{"internalType":"string","name":"certType","type":"string"},{"internalType":"string","name":"compositeHash","type":"string"}],"name":"verifyCertificate","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"string","name":"regNo","type":"string"},{"internalType":"string","name":"certType","type":"string"}],"name":"getHash","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"}]')

NAME_BLACKLIST = {
    "SUBJECT","THEORY","PRACTICAL","INTERNAL","MARKS","TOTAL",
    "YEAR","PASS","FAIL","BOARD","CERTIFICATE","SCHOOL","ROLL",
    "DATE","BIRTH","REGISTER","MEDIUM","GROUP","CODE","ISSUED",
    "EXAMINATIONS","AUTHORITY","GOVERNMENT","OBTAINED","SESSION",
    "CANDIDATE","RESULT","STATE","DEPARTMENT","HIGHER","SECONDARY",
    "TAMILNADU","CHENNAI","INSTRUCTION","GENERAL","FIRST","SECOND",
    "PROVISIONAL","STANDARD","LEAVING","DIRECTORATE",
}

# ── Cached web3 connection ─────────────────────────────────────────────────
_w3_instance   = None
_contract_inst = None

def get_contract():
    global _w3_instance, _contract_inst
    if _w3_instance is None or not _w3_instance.is_connected():
        _w3_instance = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
        if not _w3_instance.is_connected():
            raise ConnectionError("Cannot connect to Sepolia. Check internet.")
        _contract_inst = _w3_instance.eth.contract(
            address=Web3.to_checksum_address(CONTRACT_ADDRESS),
            abi=ABI,
        )
    return _w3_instance, _contract_inst

# ── Utilities ──────────────────────────────────────────────────────────────

def clean_text(text) -> str:
    if text is None:
        return ""
    text = text.replace("\n", " ").replace("\x00", " ")
    text = re.sub(r'[^A-Za-z0-9 /:&()-]', '', text)
    return text.strip()

def clean_cell(cell) -> str:
    return re.sub(r"\s+", " ", (cell or "")).strip()

def normalise(value) -> str:
    return re.sub(r"\s+", "", str(value or "").upper().strip())

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def extract_register_no(text: str) -> Optional[str]:
    """
    Robust register number extraction — tries multiple patterns in priority order.
    Handles both 10th (alphanumeric XM24R...) and 12th (10-digit numeric) formats.
    """
    patterns = [
        r'PERMANENT\s+REGISTER\s+NO[^A-Z0-9]{0,20}([A-Z]{2}\d{2}[A-Z]\d{7,12})',
        r'PERMANENT\s+REGISTER\s+NO[^0-9]{0,20}(\d{10})',
        r'\b(XM\d{2}[A-Z]\d{7,12})\b',
        r'\b([A-Z]{2}\d{2}[A-Z]\d{7,12})\b',
        r'\b(\d{10})\b',
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    return None

def compute_hash(name, register_no, total_marks, cert_type, session) -> str:
    n      = normalise(name)
    r      = normalise(register_no)
    t      = normalise(total_marks)
    c      = normalise(cert_type)
    corona = (normalise(session) == "MAR2021")
    if corona:
        return sha256(f"{n}||{r}||{c}")
    return sha256(f"{n}||{r}||{t}||{c}")

# ── PDF type detection ─────────────────────────────────────────────────────

def detect_pdf_type(pdf_path: str) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        page   = pdf.pages[0]
        tables = page.extract_tables()
        words  = page.extract_words()
        text   = page.extract_text() or ""
    is_image = len(tables) == 0 and len(text.strip()) < 100
    return {
        "table_count":    len(tables),
        "word_count":     len(words),
        "is_image_based": is_image,
    }

# ── OCR extraction (image-based PDFs) ─────────────────────────────────────

def ocr_extract(pdf_path: str, cert_type: str) -> dict:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    with pdfplumber.open(pdf_path) as pdf:
        pil_img = pdf.pages[0].to_image(resolution=200).original

    ocr_raw  = pytesseract.image_to_string(pil_img)
    ocr_text = clean_text(ocr_raw)

    student = {
        "name": None, "session": None,
        "permanent_register_no": None,
        "total_marks": None,
        "extraction_method": "OCR",
    }

    # Session
    m = re.search(r'\b((?:MAR|APR|MAY|NOV)\s+20\d{2})\b', ocr_text, re.I)
    if m:
        student["session"] = m.group(1).upper()

    # Register number — use robust extractor
    reg = extract_register_no(ocr_text)
    if reg:
        student["permanent_register_no"] = reg

    # Total marks
    if cert_type == "10":
        m = re.search(r'\b([1-5]\d{2})\s+(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)', ocr_text, re.I)
        if m:
            student["total_marks"] = int(m.group(1))
        else:
            nums = re.findall(r'\b([1-5]\d{2})\b', ocr_text)
            candidates = [int(n) for n in nums if 300 <= int(n) <= 600]
            if candidates:
                student["total_marks"] = candidates[-1]
    else:
        parts = re.split(r'Second\s+Year', ocr_text, flags=re.I)
        if len(parts) >= 2:
            m = re.search(r'TOTAL\s+MARKS\s+(0\d{3})', parts[-1], re.I)
            if m:
                student["total_marks"] = int(m.group(1))
        if student["total_marks"] is None:
            all_totals = re.findall(r'TOTAL\s+MARKS\s+(0\d{3})', ocr_text, re.I)
            if len(all_totals) >= 2:
                student["total_marks"] = int(all_totals[-1])
            elif len(all_totals) == 1:
                student["total_marks"] = int(all_totals[0])
        if student["total_marks"] is None:
            all_0xxx = re.findall(r'\b(0\d{3})\b', ocr_text)
            if all_0xxx:
                student["total_marks"] = int(all_0xxx[-1])

    # Name
    m = re.search(
        r'Name\s+of\s+the\s+Candidate(.{0,200}?)((?:MAR|APR|MAY|NOV)\s+20\d{2})',
        ocr_text, re.I | re.DOTALL)
    if m:
        for candidate in re.findall(r'\b([A-Z][A-Z\s\.]{2,30})\b', m.group(1)):
            c = candidate.strip()
            if c and len(c) > 3 and not any(kw in c.upper() for kw in NAME_BLACKLIST):
                student["name"] = c
                break

    if not student["name"]:
        found_label = False
        for line in ocr_raw.split("\n"):
            ls = line.strip()
            if "Name of the Candidate" in ls or "Candidate" in ls:
                found_label = True
                continue
            if found_label:
                if not ls:
                    continue
                if re.match(r'^[A-Z][A-Z\s\.]{4,30}$', ls):
                    if not any(kw in ls.upper() for kw in NAME_BLACKLIST):
                        student["name"] = ls
                        break
                if any(kw in ls for kw in ["Mother", "Father", "Guardian"]):
                    break

    return student

# ── 10th table extraction ──────────────────────────────────────────────────

def table_extract_10th(pdf_path: str) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        page   = pdf.pages[0]
        tables = page.extract_tables()
        text   = clean_text(page.extract_text() or "")

    student = {
        "name": None, "session": None,
        "permanent_register_no": None,
        "total_marks": None,
        "extraction_method": "TABLE",
    }

    # Name and session from table
    for table in tables:
        for row in table:
            rc = [clean_cell(c) for c in row if c]
            if len(rc) >= 2:
                m = re.search(r'\b((?:MAR|APR|MAY|NOV)\s+20\d{2})\b', rc[1], re.I)
                if m and re.match(r'^[A-Z][A-Z\s\.]{2,35}$', rc[0]):
                    if "CANDIDATE" not in rc[0].upper():
                        student["name"]    = rc[0].strip()
                        student["session"] = m.group(1).upper()
                        break
        if student["name"]:
            break

    # Register number — robust extractor
    reg = extract_register_no(text)
    if reg:
        student["permanent_register_no"] = reg

    # Total marks
    total = None
    for table in tables:
        for row in table:
            rc = [clean_cell(c) for c in row if c]
            if not rc:
                continue
            if "TOTAL" in rc[0].upper():
                for cell in rc[1:]:
                    nums = re.findall(r'\b([1-5]\d{2})\b', cell)
                    for n_val in nums:
                        v = int(n_val)
                        if 100 <= v <= 600:
                            total = v
                            break
                    if total:
                        break
            if total:
                break
        if total:
            break

    # Fallback from text
    if not total:
        m = re.search(r'TOTAL\s+MARKS\s+(\d{3})', text, re.I)
        if m:
            total = int(m.group(1))

    student["total_marks"] = total
    return student

# ── 12th table extraction ──────────────────────────────────────────────────

def table_extract_12th(pdf_path: str) -> dict:
    all_tables, full_text = [], ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"
            tables = page.extract_tables()
            if tables:
                all_tables.extend(tables)

    student = {
        "name": None, "session": None,
        "permanent_register_no": None,
        "total_marks": None,
        "extraction_method": "TABLE",
    }

    # Name and session
    for table in all_tables:
        for row in table:
            rc = [clean_cell(c) for c in row if c]
            if len(rc) >= 2:
                m = re.search(r'\b((?:MAR|APR|MAY|NOV)\s+20\d{2})\b', rc[1], re.I)
                if m and re.match(r'^[A-Z][A-Z\s\.]{2,35}$', rc[0]):
                    if "CANDIDATE" not in rc[0].upper():
                        student["name"]    = rc[0].strip()
                        student["session"] = m.group(1).upper()
                        break
        if student["name"]:
            break

    # Register number — robust extractor on full text
    reg = extract_register_no(clean_text(full_text))
    if reg:
        student["permanent_register_no"] = reg

    # Total marks — second year section
    if all_tables:
        in_second_year = False
        sy_total       = None
        marks_table    = max(all_tables, key=lambda t: len(t))

        for row in marks_table:
            cells = [clean_cell(c) for c in row]
            if not cells:
                continue
            first = cells[0].upper().strip()
            if first == "FIRST YEAR":
                in_second_year = False; continue
            if first == "SECOND YEAR":
                in_second_year = True; continue
            if "TOTAL MARKS" in first and in_second_year:
                raw = cells[1] if len(cells) > 1 else ""
                m = re.search(r'\b(0\d{3})\b', raw)
                if m:
                    sy_total = int(m.group(1))
        student["total_marks"] = sy_total

    if student["total_marks"] is None:
        m = re.search(r'Second\s+Year.*?TOTAL\s+MARKS\s+(0\d{3})', full_text, re.I | re.DOTALL)
        if m:
            student["total_marks"] = int(m.group(1))

    if not student["session"]:
        m = re.search(r'\b((?:MAR|APR|MAY|NOV)\s+20\d{2})\b', full_text, re.I)
        if m:
            student["session"] = m.group(1).upper()

    return student

# ── Blockchain verification ────────────────────────────────────────────────

def verify_on_blockchain(reg_no: str, cert_type: str, fresh_hash: str) -> dict:
    _, contract = get_contract()
    stored_hash = contract.functions.getHash(reg_no, cert_type).call()

    if not stored_hash:
        return {
            "verdict":     "NOT_FOUND",
            "stored_hash": None,
            "fresh_hash":  fresh_hash,
            "match":       False,
        }

    match = (stored_hash.lower() == fresh_hash.lower())
    return {
        "verdict":     "GENUINE" if match else "TAMPERED",
        "stored_hash": stored_hash,
        "fresh_hash":  fresh_hash,
        "match":       match,
    }