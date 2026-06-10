#!/usr/bin/env python3
"""
Compare Schedule addresses (File B) vs Foreclosures addresses (File A).
Run: python3 /Users/jarvis/Documents/Claude/Foreclosures/compare_addresses.py
Results written to: /Users/jarvis/Documents/Claude/Foreclosures/address_comparison_results.txt
"""
import json
import re
import sys

TOOL_RESULTS_BASE = "/sessions/admiring-bold-cerf/mnt/.claude/projects/-Users-jarvis-Library-Application-Support-Claude-local-agent-mode-sessions-268b828e-c1c0-448d-94e8-a0302b790e3b-8d255375-d05b-4faa-8059-e6ac1fa19239-local-b5e44163-918f-42ff-b2d8-0cd4db24b5a1-outputs/f409d1c1-259c-4bbc-9ed4-b2a4d1892e64/tool-results"
FILE_A = f"{TOOL_RESULTS_BASE}/mcp-9b98eabc-cd07-45a7-aa40-23a7fcf3ced5-read_file_content-1781008506431.txt"
FILE_B = f"{TOOL_RESULTS_BASE}/mcp-9b98eabc-cd07-45a7-aa40-23a7fcf3ced5-read_file_content-1781008507187.txt"
OUT_FILE = "/sessions/admiring-bold-cerf/mnt/Foreclosures/address_comparison_results.txt"

def make_key(addr):
    """Lowercase, take house_number + first_street_word (e.g. '714 bunker')"""
    addr = addr.strip().lower()
    parts = addr.split()
    if len(parts) >= 2 and re.match(r'^\d', parts[0]):
        return parts[0] + ' ' + parts[1]
    return None

COUNTY_NAMES = {
    'stafford', 'spotsylvania', 'fredericksburg', 'caroline', 'fauquier',
    'culpeper', 'king george', 'hanover', 'richmond', 'chesterfield',
    'henrico', 'louisa', 'orange', 'new kent', 'fredericksburg city',
    'stafford county', 'spotsylvania county'
}
TRUSTEE_CODES = {
    'ras', 'logs', 'bhl', 'ap', 'bs', 'gg', 'ra', 'sls', 'siw', 'dr',
    'wp', 'wlh', 'lenox', 'orlans', 'tromberg', 'servicelink', 'evans',
    'gemini', 'auction.com', 'xome', 'realtybid', 'dubose', 'mwc',
    'reid', 'paragon', 'surety', 'snider', 'cgd', 'mclemore', 'oberski',
    'jones', 'thomas', 'buck', 'sisk', 'vylla solutions', 'grant', 'hoa'
}

def is_valid_address(val):
    """Filter non-addresses"""
    if not val:
        return False
    val = val.strip()
    if not val:
        return False
    # Must start with a digit
    if not re.match(r'^\d', val):
        return False
    # Skip dollar amounts
    if re.match(r'^\d[\d,\.]*\s*\$', val):
        return False
    # Skip dates (MM/DD/YYYY)
    if re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}', val):
        return False
    # Skip times (HH:MM)
    if re.match(r'^\d{1,2}:\d{2}', val):
        return False
    # Skip phone numbers
    if re.match(r'^\d{3}[-\s]\d{3}', val) or re.match(r'^\(\d{3}\)', val):
        return False
    # Must have at least one letter (street name)
    if not re.search(r'[A-Za-z]', val):
        return False
    # Must be a reasonable length
    if len(val) < 8 or len(val) > 150:
        return False
    return True

lines_out = []
def log(msg):
    print(msg)
    lines_out.append(msg)

# ---- FILE A: FredericksburgForeclosures (Foreclosures tab) ----
log("Reading File A (Foreclosures)...")
try:
    with open(FILE_A, 'r', encoding='utf-8') as f:
        raw_a = f.read()
except FileNotFoundError:
    log(f"ERROR: File A not found at {FILE_A}")
    sys.exit(1)

try:
    data_a = json.loads(raw_a)
    content_a = data_a.get('fileContent', raw_a)
except:
    content_a = raw_a

log(f"File A raw content length: {len(content_a)} chars")

# File A: pipe-delimited rows separated by \n (within the JSON string, \n is encoded as literal \n or &#10;)
# Try multiple separators
if '&#10;' in content_a:
    rows_a_raw = content_a.split('&#10;')
    log(f"File A: split on &#10;, {len(rows_a_raw)} rows")
elif '\n' in content_a:
    rows_a_raw = content_a.split('\n')
    log(f"File A: split on newline, {len(rows_a_raw)} rows")
else:
    # Single line - try to find row pattern
    rows_a_raw = [content_a]
    log("File A: single line, treating as one row")

# Extract column A (first column before first pipe, or between first two pipes if row starts with |)
fc_addresses = []
header_found = False
for row in rows_a_raw:
    row = row.strip()
    if not row or ':-:' in row:
        continue
    if 'Address' in row and 'County' in row:
        header_found = True
        continue
    if row.startswith('|'):
        parts = [p.strip() for p in row.split('|')]
        parts = [p for p in parts if p != '']
        if parts:
            addr = parts[0]
            if is_valid_address(addr):
                fc_addresses.append(addr)
    else:
        # First pipe-delimited field
        parts = row.split('|')
        addr = parts[0].strip()
        if is_valid_address(addr):
            fc_addresses.append(addr)

log(f"File A: {len(fc_addresses)} address strings extracted")

# Build unique key set
fc_keys = {}  # key -> original address
for addr in fc_addresses:
    k = make_key(addr)
    if k and k not in fc_keys:
        fc_keys[k] = addr

log(f"File A: {len(fc_keys)} unique address keys")

# ---- FILE B: Buying Virginia Muffin (Schedule tab) ----
log("\nReading File B (Schedule)...")
try:
    with open(FILE_B, 'r', encoding='utf-8') as f:
        raw_b = f.read()
except FileNotFoundError:
    log(f"ERROR: File B not found at {FILE_B}")
    sys.exit(1)

try:
    data_b = json.loads(raw_b)
    content_b = data_b.get('fileContent', raw_b)
except:
    content_b = raw_b

log(f"File B raw content length: {len(content_b)} chars")

# Split on &#10; (HTML entity row separator confirmed from grep analysis)
if '&#10;' in content_b:
    rows_b_raw = content_b.split('&#10;')
    log(f"File B: split on &#10;, {len(rows_b_raw)} rows")
else:
    rows_b_raw = content_b.split('\n')
    log(f"File B: split on newline, {len(rows_b_raw)} rows")

# Column 4 (index 3) is Address when row format is: | Date | Time | County | Address | ...
# Some rows have address directly (no full date/time/county)
sched_addresses_raw = []
for row in rows_b_raw:
    row = row.strip()
    if not row or ':-:' in row or 'NO_HEADER' in row or 'NO\\_HEADER' in row:
        continue
    if 'Date' in row and 'Time' in row and 'Address' in row:
        continue  # header row

    parts = [p.strip() for p in row.split('|')]
    parts = [p for p in parts]  # keep empties for position

    # Remove leading/trailing empty from pipe boundaries
    if parts and parts[0] == '':
        parts = parts[1:]
    if parts and parts[-1] == '':
        parts = parts[:-1]

    addr = None
    if len(parts) >= 4:
        # Standard format: Date | Time | County | Address | Source
        candidate = parts[3].strip() if len(parts) > 3 else ''
        if is_valid_address(candidate):
            addr = candidate
        # Also check if this might be historical format: blank | date | time | county | address
        elif parts[0] == '' and len(parts) >= 5:
            candidate2 = parts[4].strip()
            if is_valid_address(candidate2):
                addr = candidate2

    if addr:
        sched_addresses_raw.append(addr)

log(f"File B: {len(sched_addresses_raw)} raw addresses extracted")

# Deduplicate by key
sched_unique = {}  # key -> original address
for addr in sched_addresses_raw:
    # Normalize: strip trailing spaces, tabs
    addr = re.sub(r'\s+', ' ', addr).strip()
    k = make_key(addr)
    if k and k not in sched_unique:
        sched_unique[k] = addr

log(f"File B: {len(sched_unique)} unique address keys")

# ---- COMPARISON ----
fc_key_set = set(fc_keys.keys())
sched_key_set = set(sched_unique.keys())

matched_keys = sched_key_set & fc_key_set
missing_keys = sched_key_set - fc_key_set

log(f"\n{'='*50}")
log(f"RESULTS")
log(f"{'='*50}")
log(f"Total unique Schedule addresses: {len(sched_unique)}")
log(f"Total Foreclosures unique address keys: {len(fc_key_set)}")
log(f"Match count: {len(matched_keys)}")
log(f"Missing (Schedule NOT in Foreclosures): {len(missing_keys)}")

prev_unique = 329
prev_matches = 50
prev_missing = 279
log(f"\nChange vs last run (prev unique={prev_unique}, prev matches={prev_matches}, prev missing={prev_missing}):")
log(f"  New Schedule addresses: {len(sched_unique) - prev_unique:+d}")
log(f"  Match change: {len(matched_keys) - prev_matches:+d}")
log(f"  Missing change: {len(missing_keys) - prev_missing:+d}")

log(f"\n{'='*50}")
log(f"MATCHED (Schedule addresses found in Foreclosures):")
log(f"{'='*50}")
for k in sorted(matched_keys):
    log(f"  {sched_unique[k]}")

log(f"\n{'='*50}")
log(f"MISSING SCHEDULE ADDRESSES (not in Foreclosures) [{len(missing_keys)} total]:")
log(f"{'='*50}")
missing_list = sorted([sched_unique[k] for k in missing_keys])
for addr in missing_list:
    log(f"  {addr}")

# Write results
with open(OUT_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines_out))
print(f"\nResults written to: {OUT_FILE}")
