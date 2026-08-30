$pyCode = @'
import os, re, sys

MIDTERM_SUBJECTS = [
    'Midterm Exam Schedule Reminder',
    'Midterm Exam Study Session',
    'Midterm Exam Essay Guidance',
    'Midterm Exam Room Assignment',
]
FINAL_SUBJECTS = [
    'Final Exam Practice Worksheet',
    'Final Exam Reminder',
]
IRRELEVANT_SUBJECTS = [
    'Campus Club Meeting Tonight',
    'Lunch Menu Update',
    'Photography Workshop Saturday',
    'Travel Reimbursement Status',
]

def locate_local_folders():
    tb_root = os.path.join(os.environ['APPDATA'], 'Thunderbird')
    profiles_ini = os.path.join(tb_root, 'profiles.ini')
    if not os.path.isfile(profiles_ini):
        print(f'EVAL_RESULT:FAIL profiles.ini not found: {profiles_ini}')
        sys.exit(0)

    sections = {}
    current = None
    with open(profiles_ini, 'r', encoding='utf-8', errors='ignore') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith(';'):
                continue
            section_match = re.match(r'^\[(.+)\]$', line)
            if section_match:
                current = section_match.group(1)
                sections.setdefault(current, {})
                continue
            if current and '=' in line:
                key, value = line.split('=', 1)
                sections[current][key.strip()] = value.strip()

    profile_entry = None
    for sec_name in sorted(sections):
        if sec_name.startswith('Profile') and sections[sec_name].get('Default') == '1':
            profile_entry = sections[sec_name]
            break
    if profile_entry is None:
        for sec_name in sorted(sections):
            if sec_name.startswith('Profile'):
                profile_entry = sections[sec_name]
                break
    if profile_entry is None:
        print('EVAL_RESULT:FAIL no [Profile*] section found in profiles.ini')
        sys.exit(0)

    profile_path = profile_entry.get('Path', '').strip()
    if not profile_path:
        print('EVAL_RESULT:FAIL default Thunderbird profile path is empty in profiles.ini')
        sys.exit(0)

    is_relative = profile_entry.get('IsRelative', '1') == '1'
    if is_relative:
        profile_dir = os.path.join(tb_root, profile_path)
    else:
        profile_dir = profile_path

    candidate = os.path.join(profile_dir, 'Mail', 'Local Folders')
    if os.path.isdir(candidate):
        return candidate

    print(f'EVAL_RESULT:FAIL unable to locate Thunderbird Local Folders directory: {candidate}')
    sys.exit(0)

def read_text(path):
    if not os.path.isfile(path):
        return ''
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()

def parse_mbox(raw_text):
    parsed = []
    for msg in re.split(r'^From - ', raw_text, flags=re.MULTILINE):
        if not msg.strip():
            continue
        status_match = re.search(r'X-Mozilla-Status:\s*([0-9a-fA-F]{4})', msg)
        status_val = int(status_match.group(1), 16) if status_match else 0
        subject_match = re.search(r'^Subject:\s*(.+)', msg, re.MULTILINE)
        subject_val = subject_match.group(1).strip() if subject_match else ''
        msgid_match = re.search(r'^Message-ID:\s*(.+)', msg, re.MULTILINE)
        msgid_val = msgid_match.group(1).strip() if msgid_match else ''
        parsed.append({
            'subject': subject_val,
            'msgid': msgid_val,
            'status': status_val,
            'starred': bool(status_val & 0x0004),
            'expunged': bool(status_val & 0x0008),
        })
    return parsed

local_folders = locate_local_folders()
inbox_path = os.path.join(local_folders, 'Bills')
trash_path = os.path.join(local_folders, 'Trash')

if not os.path.isfile(inbox_path):
    print(f'EVAL_RESULT:FAIL Bills mbox not found: {inbox_path}')
    sys.exit(0)

inbox_messages = parse_mbox(read_text(inbox_path))
trash_messages = parse_mbox(read_text(trash_path))

inbox_active = [m for m in inbox_messages if not m['expunged']]
trash_active = [m for m in trash_messages if not m['expunged']]

inbox_subjects = [m['subject'] for m in inbox_active]
trash_subjects = [m['subject'] for m in trash_active]

for subject in MIDTERM_SUBJECTS:
    matches = [m for m in inbox_active if m['subject'] == subject]
    if len(matches) != 1:
        print(f'EVAL_RESULT:FAIL expected active Bills copy of midterm subject={subject!r} got={len(matches)}')
        sys.exit(0)
    if not matches[0]['starred']:
        status_hex = format(matches[0]['status'], '04x')
        print(f'EVAL_RESULT:FAIL midterm subject not starred subject={subject!r} status=0x{status_hex}')
        sys.exit(0)

for subject in FINAL_SUBJECTS:
    final_matches = [m for m in inbox_active if m['subject'] == subject]
    if len(final_matches) != 1:
        print(f'EVAL_RESULT:FAIL expected exactly 1 active final exam email in Bills subject={subject!r} got={len(final_matches)}')
        sys.exit(0)
    if final_matches[0]['starred']:
        print(f'EVAL_RESULT:FAIL Final Exam email should remain unstarred subject={subject!r}')
        sys.exit(0)

expected_remaining = sorted(MIDTERM_SUBJECTS + FINAL_SUBJECTS)
actual_remaining = sorted(inbox_subjects)
if actual_remaining != expected_remaining:
    print(f'EVAL_RESULT:FAIL active Bills subjects mismatch got={actual_remaining} expected={expected_remaining}')
    sys.exit(0)

for subject in IRRELEVANT_SUBJECTS:
    if subject in inbox_subjects:
        print(f'EVAL_RESULT:FAIL irrelevant subject still active in Bills subject={subject!r}')
        sys.exit(0)

    inbox_versions = [m for m in inbox_messages if m['subject'] == subject]
    trash_versions = [m for m in trash_active if m['subject'] == subject]
    deleted_ok = (
        any(m['expunged'] for m in inbox_versions)
        or len(trash_versions) == 1
        or not inbox_versions
    )
    if not deleted_ok:
        print(f'EVAL_RESULT:FAIL irrelevant subject was not deleted subject={subject!r}')
        sys.exit(0)

total_starred_remaining = sum(1 for m in inbox_active if m['starred'])
if total_starred_remaining != 4:
    print(f'EVAL_RESULT:FAIL expected exactly 4 starred remaining emails got={total_starred_remaining}')
    sys.exit(0)

print(
    'EVAL_RESULT:PASS '
    f'Bills={actual_remaining} Trash={trash_subjects} '
    f'Starred={total_starred_remaining}'
)
'@

Stop-Process -Name thunderbird -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$pyCode | py -3 -W ignore -
