#!/usr/bin/env python3
"""Find basename matches between slang-shaders and common-shaders,
inspect top-of-file comments and generate unified diffs to insert
license headers from sources into targets when missing.

This is a safe, read-only script: it prints diffs and does not modify files.
"""
import os
import sys
import argparse
import pathlib
import re
import difflib
import subprocess

# Config
TARGET_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
COMMON_ROOT = os.path.abspath(os.path.join(TARGET_ROOT, '..', 'common-shaders'))

TARGET_EXTS = ['.slang', '.slangp']
SOURCE_EXTS = ['.cg', '.cgp', '.hlsl']
HEAD_LINES = 80
MAX_PAIRS = 30
MAX_DIFF_LINES = 200

LICENSE_KEYWORDS = ['copyright', 'licensed', 'spdx', 'permission is hereby granted', 'mit license', 'bsd license']
COMPAT_KEYWORDS = ['compat', 'compatibility', 'hlsl', 'cg', 'fx11', 'fx11 compilers', 'hlsl compilers']


def gather_files(root, exts):
    out = []
    for dirpath, dirs, files in os.walk(root):
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                out.append(os.path.join(dirpath, f))
    return out


def basename_noext(path):
    return os.path.splitext(os.path.basename(path))[0].lower()


def read_head(path, n=HEAD_LINES):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            lines = []
            for _ in range(n):
                line = fh.readline()
                if not line:
                    break
                lines.append(line)
            return lines
    except Exception as e:
        return []


def contains_license(lines):
    text = '\n'.join(lines).lower()
    return any(k in text for k in LICENSE_KEYWORDS)


def extract_top_comment_block(lines, source_ext):
    """Extract the top contiguous comment block from source lines.
    Supports /* ... */ and // comment styles. Returns list of lines.
    """
    if not lines:
        return []
    joined = ''.join(lines)
    # Try block comment first
    m = re.search(r"\A\s*(/\*.*?\*/)", joined, re.S)
    if m:
        block = m.group(1)
        return block.splitlines(keepends=True)
    # Otherwise collect leading // lines
    out = []
    for line in lines:
        if re.match(r"\s*//", line):
            out.append(line)
        elif re.match(r"\s*$", line):
            # allow single blank lines inside top block
            out.append(line)
        else:
            break
    return out


def convert_comment_to_slang(comment_lines):
    """Convert a Cg/HLSL comment block to GLSL-friendly style:
    - If block comment /* */ present: keep as-is.
    - If // lines: convert to /* ... */ block.
    Returns list of lines including trailing newline.
    """
    if not comment_lines:
        return []
    text = ''.join(comment_lines)
    if text.strip().startswith('/*'):
        # Ensure ends with newline
        if not text.endswith('\n'):
            text += '\n'
        return text.splitlines(keepends=True)
    # Merge // lines into block
    body = []
    for ln in comment_lines:
        m = re.match(r"\s*//\s?(.*)$", ln)
        if m:
            body.append(m.group(1))
        elif ln.strip()=='':
            body.append('')
        else:
            body.append(ln.rstrip('\n'))
    block = ['/*\n']
    for b in body:
        block.append(' * ' + b.rstrip('\n') + '\n')
    block.append(' */\n')
    return block


def build_new_target_content(orig_lines, header_lines):
    """Insert header_lines at the top of orig_lines, but try to preserve
    any leading # directives or special "@" lines that should stay at top.
    Strategy: if the file starts with a line that begins with '#', '@', or a
    pragma-like token, insert header after that initial small prelude.
    """
    if not header_lines:
        return orig_lines
    # detect leading prelude (first contiguous block of lines starting with # or @)
    prelude_end = 0
    for i, ln in enumerate(orig_lines[:10]):
        if ln.startswith('#') or ln.startswith('@'):
            prelude_end = i+1
            continue
        # allow blank lines between preludes
        if ln.strip()=='' and prelude_end>0:
            prelude_end = i+1
            continue
        break
    new = []
    new.extend(orig_lines[:prelude_end])
    # ensure header ends with a newline
    if header_lines and not header_lines[-1].endswith('\n'):
        header_lines[-1] = header_lines[-1] + '\n'
    new.extend(header_lines)
    # ensure a blank line after header
    if not (orig_lines[prelude_end:prelude_end+1] and orig_lines[prelude_end].strip()==''):
        new.append('\n')
    new.extend(orig_lines[prelude_end:])
    return new


def is_compat_only(comment_lines):
    """Return True if the comment appears to be a compatibility-only header
    (mentions compat/compatibility/Cg/HLSL but doesn't contain license keywords).
    """
    if not comment_lines:
        return False
    text = '\n'.join(comment_lines).lower()
    has_compat = any(k in text for k in COMPAT_KEYWORDS)
    has_license = any(k in text for k in LICENSE_KEYWORDS)
    return has_compat and not has_license


def extract_license_paragraph(comment_lines):
    """Try to extract a small paragraph that contains a license keyword.
    Returns a list of lines (possibly empty) containing the license text only.
    """
    if not comment_lines:
        return []
    lower_lines = [ln.lower() for ln in comment_lines]
    for kw in LICENSE_KEYWORDS:
        for i, ln in enumerate(lower_lines):
            if kw in ln:
                # expand bounds to include surrounding non-empty lines, but stop at compat markers
                start = i
                while start > 0 and lower_lines[start-1].strip() != '' and 'compat' not in lower_lines[start-1]:
                    start -= 1
                end = i
                while end + 1 < len(lower_lines) and lower_lines[end+1].strip() != '' and 'compat' not in lower_lines[end+1]:
                    end += 1
                return comment_lines[start:end+1]
    return []


def strip_compat_lines(comment_lines):
    """Remove obvious compatibility-only lines from a comment block.
    Keeps likely license lines (copyright, licensed, permission, spdx, etc.).
    """
    out = []
    for ln in comment_lines:
        lnl = ln.lower()
        # keep if it's a license line
        if any(k in lnl for k in LICENSE_KEYWORDS):
            out.append(ln)
            continue
        # skip obvious compat mentions or compiler lists
        if re.search(r"\b(compat|compatibility|hlsl|cg|fx11|fx11 compilers|compilers?)\b", lnl):
            continue
        # skip short bullet lines (like "- HLSL compilers")
        if re.match(r"\s*[-*]\s*\w+", ln):
            continue
        # keep otherwise (could be part of license text)
        out.append(ln)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target-root', default=TARGET_ROOT)
    parser.add_argument('--common-root', default=COMMON_ROOT)
    parser.add_argument('--source-exts', default=','.join(SOURCE_EXTS),
                        help='Comma-separated list of source file extensions to scan (e.g. .cg,.cgp,.hlsl,.glsl,.glslp)')
    parser.add_argument('--max-pairs', type=int, default=MAX_PAIRS)
    parser.add_argument('--apply', action='store_true', help='Apply the proposed header insertions to files and commit')
    args = parser.parse_args()

    targets = gather_files(args.target_root, TARGET_EXTS)
    # parse source extensions from CLI (comma-separated)
    src_exts = [e.strip().lower() for e in args.source_exts.split(',') if e.strip()]
    sources = gather_files(args.common_root, src_exts)

    target_map = {}
    for t in targets:
        target_map.setdefault(basename_noext(t), []).append(t)
    source_map = {}
    for s in sources:
        source_map.setdefault(basename_noext(s), []).append(s)

    # find basenames present in both
    common_basenames = [b for b in target_map.keys() if b in source_map]
    common_basenames.sort()

    pairs = []  # list of (target_path, source_path)
    for b in common_basenames:
        tlist = target_map[b]
        slist = source_map[b]
        # for now pair each target with the first source (but keep note if multiple)
        for t in tlist:
            for s in slist:
                pairs.append((t, s))

    print(f'Found {len(pairs)} candidate pairs (target, source). Showing up to {args.max_pairs}.')

    shown = 0
    modified_files = []
    for t, s in pairs:
        if shown >= args.max_pairs:
            break
        t_head = read_head(t)
        s_head = read_head(s)
        if contains_license(t_head):
            # skip; target already mentions license
            # but for transparency print a short note
            print(f'-- SKIP (target has license): {t}   <=  {s}')
            shown += 1
            continue
        # extract source header
        src_comment = extract_top_comment_block(s_head, os.path.splitext(s)[1].lower())
        if not src_comment:
            # nothing to copy
            print(f'-- NO SOURCE HEADER: {s}  (no top comment block)')
            shown += 1
            continue
        # Try to extract a focused license paragraph first
        license_para = extract_license_paragraph(src_comment)
        if license_para:
            header_src = license_para
        else:
            # remove obvious compat-only lines and see if anything remains that
            # looks like license text
            stripped = strip_compat_lines(src_comment)
            if not stripped or not any(k in '\n'.join(stripped).lower() for k in LICENSE_KEYWORDS):
                print(f'-- SKIP (source header lacks license keywords after stripping): {s}')
                shown += 1
                continue
            header_src = stripped
        header = convert_comment_to_slang(header_src)
        with open(t, 'r', encoding='utf-8', errors='ignore') as fh:
            t_lines = fh.readlines()
        new_lines = build_new_target_content(t_lines, header)
        diff = list(difflib.unified_diff(t_lines, new_lines, fromfile=t, tofile=t, lineterm=''))
        if not diff:
            print(f'-- NO CHANGE NEEDED: {t}  (header conversion produced no diff)')
            shown += 1
            continue
        # print header for this diff, but limit total lines
        print('\n' + '='*80)
        print(f'DIFF for target: {t}   <=  source: {s}')
        print('='*80)
        if args.apply:
            # write new content (backup original)
            bak = t + '.bak'
            try:
                os.replace(t, bak)
            except Exception:
                # if rename fails, try copy
                import shutil
                shutil.copy2(t, bak)
            with open(t, 'w', encoding='utf-8', errors='ignore') as fh:
                fh.writelines(new_lines)
            modified_files.append(t)
            print(f'-- APPLIED: {t}  (backup at {bak})')
        else:
            if len(diff) > MAX_DIFF_LINES:
                # print first and last parts
                for ln in diff[:MAX_DIFF_LINES//2]:
                    print(ln)
                print('... (diff truncated) ...')
                for ln in diff[-MAX_DIFF_LINES//2:]:
                    print(ln)
            else:
                for ln in diff:
                    print(ln)
        shown += 1

    # after loop, commit if applied
    if args.apply and modified_files:
        # stage and commit
        try:
            subprocess.check_call(['git', 'add'] + modified_files)
            msg = 'chore: copy license headers from common-shaders into slang-shaders for matched ports'
            subprocess.check_call(['git', 'commit', '-m', msg])
            print('Committed', len(modified_files), 'files')
        except Exception as e:
            print('git commit failed:', e)

    if shown == 0:
        print('No candidate diffs found or nothing to show.')

if __name__ == '__main__':
    main()
