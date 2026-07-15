"""
store.py — Extract certificate data and store composite hash on blockchain.
- Prevents duplicate storage (checks if already stored before sending tx)
- Faster: single-pass extraction, no redundant loops
- Better register number extraction
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
PRIVATE_KEY      = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS   = os.getenv("WALLET_ADDRESS")
RPC_URL          = os.getenv("RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
CHAIN_ID         = int(os.getenv("CHAIN_ID", "11155111"))

ABI = json.loads('[{"inputs":[{"internalType":"string","name":"regNo","type":"string"},{"internalType":"string","name":"certType","type":"string"},{"internalType":"string","name":"compositeHash","type":"string"}],"name":"storeCertificate","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"string","name":"regNo","type":"string"},{"internalType":"string","name":"certType","type":"string"},{"internalType":"string","name":"compositeHash","type":"string"}],"name":"verifyCertificate","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"string","name":"regNo","type":"string"},{"internalType":"string","name":"certType","type":"string"}],"name":"getHash","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"}]')

KNOWN_SUBJECTS_12 = {
    "TAMIL","ENGLISH","PHYSICS","CHEMISTRY","MATHEMATICS",
    "COMPUTER SCIENCE","BIOLOGY","BOTANY","ZOOLOGY",
    "ACCOUNTANCY","COMMERCE","ECONOMICS","HISTORY",
    "GEOGRAPHY","POLITICAL SCIENCE","BUSINESS MATHEMATICS",
}
KNOWN_SUBJECTS_10 = ["TAMIL","ENGLISH","MATHEMATICS","SCIENCE","SOCIAL SCIENCE","OPTIONAL LANGUAGE"]
NAME_BLACKLIST = {
    "SUBJECT","THEORY","PRACTICAL","INTERNAL","MARKS","TOTAL",
    "YEAR","PASS","FAIL","BOARD","CERTIFICATE","SCHOOL","ROLL",
    "DATE","BIRTH","REGISTER","MEDIUM","GROUP","CODE","ISSUED",
    "EXAMINATIONS","AUTHORITY","GOVERNMENT","OBTAINED","SESSION",
    "CANDIDATE","RESULT",
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

def safe_int(val) -> Optional[int]:
    try:
        return int(str(val).strip())
    except Exception:
        return None

def extract_mark_from_cell(cell: str) -> Optional[int]:
    if not cell:
        return None
    part = cell.split("(")[0].strip()
    m = re.match(r"^(\d{2,3})$", part)
    return int(m.group(1)) if m and int(m.group(1)) <= 100 else None

def generate_hash(value) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(str(value).encode()).hexdigest()

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
        r'\bPERMANENT\s+REGISTER\s+NO[^A-Z0-9]{0,20}([A-Z]{2}\d{2}[A-Z]\d{7,12})\b',
        r'\bPERMANENT\s+REGISTER\s+NO[^0-9]{0,20}(\d{10})\b',
        r'\b(XM\d{2}[A-Z]\d{7,12})\b',
        r'\b([A-Z]{2}\d{2}[A-Z]\d{7,12})\b',
        r'\b(\d{10})\b',
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    return None

def compute_composite_hash(name, register_no, total_marks, cert_type, session) -> dict:
    n      = normalise(name)
    r      = normalise(register_no)
    t      = normalise(total_marks)
    c      = normalise(cert_type)
    corona = (session == "MAR 2021")

    composite = sha256(f"{n}||{r}||{c}") if corona else sha256(f"{n}||{r}||{t}||{c}")
    note      = ("Corona batch MAR 2021 — total_marks excluded" if corona
                 else "Full hash — name + register_no + total_marks + cert_type")

    return {
        "cert_type":        cert_type,
        "name_hash":        generate_hash(name),
        "number_hash":      generate_hash(register_no),
        "total_marks_hash": generate_hash(total_marks) if not corona else None,
        "composite_hash":   composite,
        "hash_note":        note,
        "_fields_used": {
            "name":        name,
            "register_no": register_no,
            "total_marks": total_marks if not corona else "N/A (corona batch)",
            "cert_type":   cert_type,
        },
    }

# ── 10th extraction ────────────────────────────────────────────────────────

def extract_10th(pdf_path: str) -> dict:
    all_tables, full_text = [], ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
            tables = page.extract_tables()
            if tables:
                all_tables.extend(tables)

    clean_full = clean_text(full_text)
    info       = _parse_10th(clean_full, all_tables)

    name    = info.get("name")
    number  = info.get("number")
    reg_no  = info.get("permanent_register_no") or number
    session = info.get("session", "")
    total   = info.get("total_marks")

    hashes = compute_composite_hash(
        name=name, register_no=reg_no,
        total_marks=total, cert_type="10", session=session,
    )
    return {
        "cert_type": "10th (SSLC)",
        "student": {
            "name": name, "number": number,
            "permanent_register_no": reg_no,
            "session": session, "total_marks": total,
        },
        "subjects": info.get("subjects", []),
        "note": "Corona batch — PASS/FAIL only" if session == "MAR 2021" else None,
        "hashes": hashes,
    }

def _parse_10th(text, tables) -> dict:
    data = {}

    # Name and session
    for table in tables:
        for row in table:
            row_clean = [clean_text(c) for c in row if c]
            if len(row_clean) >= 2:
                if re.search(r'(MAR|APR|MAY|NOV)\s+\d{4}', row_clean[1]):
                    if re.match(r'^[A-Z][A-Z\s\.]{2,35}$', row_clean[0]):
                        data["name"]    = row_clean[0]
                        data["session"] = row_clean[1]
                        break
        if data.get("name"):
            break

    # Register number — use robust extractor
    reg = extract_register_no(text)
    if reg:
        data["permanent_register_no"] = reg
        if re.match(r'^\d+$', reg):
            data["number"] = reg

    # Total marks
    total = None
    for table in tables:
        for row in table:
            row_cells = [clean_text(c) for c in row if c]
            row_text  = " ".join(row_cells).upper()
            if "TOTAL" in row_text:
                m = re.search(r'\b([1-5]\d{2})\b', row_text)
                if m:
                    v = int(m.group(1))
                    if 100 <= v <= 600:
                        total = v
                        break
        if total:
            break
    if not total:
        # Try text-based pattern
        m = re.search(r'TOTAL\s+MARKS\s+(\d{3})', text, re.I)
        if m:
            total = int(m.group(1))
    data["total_marks"] = total

    # Subjects
    subjects = []
    for table in tables:
        for row in table:
            cells = [clean_text(c) for c in row if c]
            if not cells:
                continue
            subj_upper = cells[0].upper()
            if subj_upper in KNOWN_SUBJECTS_10:
                result_cell  = cells[1] if len(cells) > 1 else ""
                result_upper = result_cell.upper()
                mark_val     = None
                m = re.search(r'\b(\d{2,3})\b', result_cell)
                if m:
                    v = int(m.group(1))
                    if v <= 100:
                        mark_val = v
                pass_fail = ("PASS" if "PASS" in result_upper
                             else "FAIL" if "FAIL" in result_upper else "N/A")
                entry = {"subject": subj_upper, "result": pass_fail}
                if mark_val is not None:
                    entry["marks"] = mark_val
                subjects.append(entry)
    data["subjects"] = subjects
    return data

# ── 12th extraction ────────────────────────────────────────────────────────

def extract_12th(pdf_path: str) -> dict:
    # Collect all text for register number extraction
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"
        table = pdf.pages[0].extract_tables()[0]

    student = {
        "name": None, "session": None, "roll_no": None,
        "permanent_register_no": None, "date_of_birth": None,
        "medium": None, "school": None,
    }
    in_second_year = False
    sy_subjects, sy_total, sy_result = [], None, None

    for row in table:
        cells = [clean_cell(c) for c in row]
        if not cells or not cells[0]:
            continue
        first = cells[0].upper()

        if not student["session"] and len(cells) > 3:
            m = re.search(r'\b((?:MAR|APR|MAY|NOV)\s+20\d{2})\b', cells[3], re.I)
            if m:
                student["session"] = m.group(1).upper()

        if first == "FIRST YEAR":
            in_second_year = False; continue
        if first == "SECOND YEAR":
            in_second_year = True; continue

        if in_second_year and "TOTAL MARKS" in first:
            raw = cells[1] if len(cells) > 1 else ""
            m = re.search(r'\b(0\d{3})\b', raw)
            if m:
                sy_total = int(m.group(1))
            sy_result = "PASS" if "PASS" in cells[-1].upper() else "FAIL"
            continue

        if in_second_year and cells[0].upper() in KNOWN_SUBJECTS_12:
            theory    = safe_int(cells[1]) if len(cells) > 1 else None
            practical = safe_int(cells[2]) if len(cells) > 2 else None
            internal  = safe_int(cells[3]) if len(cells) > 3 else None
            total_c   = extract_mark_from_cell(cells[5]) if len(cells) > 5 else None
            entry = {"subject": cells[0].upper(), "theory": theory}
            if practical:
                entry["practical"] = practical
            entry["internal"] = internal
            entry["total"]    = total_c
            sy_subjects.append(entry)
            continue

        if (not student["name"]
                and re.match(r'^[A-Z][A-Z\s\.]{2,35}$', cells[0])
                and not any(kw in first for kw in NAME_BLACKLIST)):
            student["name"] = cells[0]

        if "ROLL NO" in first:
            m = re.search(r'\b(\d{7})\b', cells[0])
            if m:
                student["roll_no"] = m.group(1)

        if re.search(r'\b(DATE\s+OF\s+BIRTH|OF\s+BIRTH)\b', first):
            m = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', cells[0])
            if m:
                student["date_of_birth"] = m.group(1)
            if len(cells) > 1:
                m = re.search(r'\b(\d{10})\b', cells[1])
                if m:
                    student["permanent_register_no"] = m.group(1)
            if len(cells) > 4:
                m = re.search(r'\b(ENGLISH|TAMIL|URDU|KANNADA|TELUGU)\b', cells[4], re.I)
                if m:
                    student["medium"] = m.group(1).upper()

        if "NAME OF THE SCHOOL" in first:
            m = re.search(
                r'((?:[A-Z\'\.]+\s+){2,}(?:MATRIC|MATRICULATION|HR\s+SEC|HIGHER\s+SEC)'
                r'[A-Z\'\s,\.]+(?:SCHOOL|COLLEGE)[A-Z\'\s,\.]*)',
                cells[0], re.I)
            if m:
                student["school"] = re.sub(r"\s+", " ", m.group(1)).strip()

    # Fallback register number from full text
    if not student["permanent_register_no"]:
        reg = extract_register_no(clean_text(full_text))
        if reg:
            student["permanent_register_no"] = reg

    hashes = compute_composite_hash(
        name=student["name"],
        register_no=student["permanent_register_no"],
        total_marks=sy_total, cert_type="12",
        session=student["session"],
    )
    return {
        "cert_type": "12th (HSC)",
        "student":   student,
        "second_year": {
            "subjects": sy_subjects,
            "total_marks": sy_total,
            "result": sy_result,
        },
        "hashes": hashes,
    }

# ── Blockchain ─────────────────────────────────────────────────────────────

def is_already_stored(reg_no: str, cert_type: str) -> bool:
    """Check blockchain if this certificate is already stored."""
    try:
        _, contract = get_contract()
        stored_hash = contract.functions.getHash(reg_no, cert_type).call()
        return bool(stored_hash and len(stored_hash) > 0)
    except Exception:
        return False

def store_on_blockchain(reg_no: str, cert_type: str, composite_hash: str) -> dict:
    """
    Store hash on blockchain.
    Returns dict with tx_hash and a flag indicating if it was already stored.
    """
    # ── Duplicate check ────────────────────────────────────────────────────
    if is_already_stored(reg_no, cert_type):
        # Already stored — retrieve existing hash and compare
        _, contract = get_contract()
        existing_hash = contract.functions.getHash(reg_no, cert_type).call()
        if existing_hash.lower() == composite_hash.lower():
            return {
                "tx_hash":       None,
                "already_stored": True,
                "existing_hash":  existing_hash,
                "message":        "Certificate already stored on blockchain. No duplicate transaction sent.",
            }
        else:
            # Hash mismatch — someone is trying to overwrite with different data
            return {
                "tx_hash":        None,
                "already_stored": True,
                "hash_conflict":  True,
                "existing_hash":  existing_hash,
                "message":        "A different certificate with this register number is already stored. Storage blocked.",
            }

    # ── New certificate — store it ─────────────────────────────────────────
    w3, contract = get_contract()
    nonce = w3.eth.get_transaction_count(WALLET_ADDRESS)
    tx = contract.functions.storeCertificate(
        reg_no, cert_type, composite_hash
    ).build_transaction({
        "chainId": CHAIN_ID,
        "gas":     200000,
        "nonce":   nonce,
    })
    signed  = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60, poll_latency=2)
    return {
        "tx_hash":        tx_hash.hex(),
        "already_stored": False,
        "message":        "Certificate stored successfully.",
    }