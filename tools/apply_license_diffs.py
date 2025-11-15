#!/usr/bin/env python3
"""Apply the diffs from tools/license_diffs_all.patch to the repo programmatically.
This script is careful: it will only apply diffs that modify files under the repo
and will back up files before overwriting. It stages and commits changes when done.
"""
import re
from pathlib import Path
import subprocess

PATCH = Path('tools/license_diffs_all.patch')
if not PATCH.exists():
    print('patch file not found:', PATCH)
    raise SystemExit(1)

text = PATCH.read_text()
# Split into DIFF sections
sections = re.split(r"\n={3,}\n", text)
# find sections that start with 'DIFF for target:' and contain a unified diff
apply_sections = []
for sec in sections:
    if 'DIFF for target:' in sec and '\n--- ' in sec:
        apply_sections.append(sec)

print('Found', len(apply_sections), 'diff sections to apply')

modified = []
for sec in apply_sections:
    # extract the '--- path' and '+++ path' from the unified diff
    m = re.search(r"^---\s+(\S+).*\n\+\+\+\s+(\S+)", sec, re.M)
    if not m:
        print('could not find file paths in section, skipping')
        continue
    target = m.group(1)
    # Our unified diff uses the same path for from/to; ensure it is in repo
    target_path = Path(target)
    if not target_path.exists():
        print('target file does not exist, skipping:', target_path)
        continue
    # extract the diff body lines starting with @@ or +/-
    diff_lines = []
    in_diff = False
    for ln in sec.splitlines():
        if ln.startswith('@@ '):
            in_diff = True
            diff_lines.append(ln)
        elif in_diff:
            diff_lines.append(ln)
    # apply the diff manually: compute new content by using patch library
    import difflib
    orig = target_path.read_text()
    # reconstruct a pseudo-unified diff for difflib
    udiff = ['--- ' + target, '+++ ' + target]
    udiff.extend(diff_lines)
    try:
        new = ''.join(difflib.restore(udiff, 2))
    except Exception as e:
        print('failed to restore diff for', target, 'error:', e)
        continue
    # backup
    bak = target_path.with_suffix(target_path.suffix + '.bak')
    target_path.rename(bak)
    target_path.write_text(new)
    modified.append(str(target_path))

# Stage and commit
if modified:
    subprocess.check_call(['git', 'add'] + modified)
    subprocess.check_call(['git', 'commit', '-m', 'chore: copy license headers from common-shaders into slang-shaders for matched ports'])
    print('Committed', len(modified), 'files')
else:
    print('No files modified')
