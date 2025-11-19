#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
from collections import OrderedDict, defaultdict

HEADER_RE = re.compile(r"^---\s*\[(\d+)\]\s*(.*?)\s*---\s*$")
PLAIN_HEADER_RE = re.compile(r"^---\s*(.*?)\s*---\s*$")  # fallback if no [n]

def load_blocks(path: Path):
    """
    Parse a log file into ordered blocks keyed primarily by the full header line.
    Also collect secondary keys: (command_name, occurrence_index).
    Returns:
      blocks_by_header: OrderedDict[str, list[str]]
      blocks_by_cmd_occ: OrderedDict[tuple[str,int], list[str]]
      header_to_cmdocc: dict[str, tuple[str,int]]
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    blocks_by_header = OrderedDict()
    current_header = None
    current_buf = []

    for ln in lines:
        if ln.strip().startswith('---') and ln.strip().endswith('---'):
            # flush previous
            if current_header is not None:
                blocks_by_header[current_header] = current_buf
            current_header = ln.strip()
            current_buf = []
        else:
            if current_header is not None:
                current_buf.append(ln)
            # else preamble lines (before first header) are ignored

    if current_header is not None:
        blocks_by_header[current_header] = current_buf

    # Build command occurrence mapping
    counts = defaultdict(int)
    blocks_by_cmd_occ = OrderedDict()
    header_to_cmdocc = {}

    for header, content in blocks_by_header.items():
        m = HEADER_RE.match(header)
        if m:
            # capture command text after index
            cmd = m.group(2).strip()
        else:
            m2 = PLAIN_HEADER_RE.match(header)
            cmd = m2.group(1).strip() if m2 else header  # fallback

        counts[cmd] += 1
        key = (cmd, counts[cmd])
        blocks_by_cmd_occ[key] = content
        header_to_cmdocc[header] = key

    return blocks_by_header, blocks_by_cmd_occ, header_to_cmdocc

def compare_files(stn_path: Path, dspic_path: Path, out_path: Path):
    stn_h, stn_cmd, stn_map = load_blocks(stn_path)
    ds_h,  ds_cmd,  ds_map  = load_blocks(dspic_path)

    # First try to match by exact header
    stn_headers = list(stn_h.keys())
    ds_headers  = list(ds_h.keys())

    common_by_header = [h for h in stn_headers if h in ds_h]
    only_stn_headers = [h for h in stn_headers if h not in ds_h]
    only_ds_headers  = [h for h in ds_headers  if h not in stn_h]

    # For blocks not matched by exact header, try command+occurrence alignment
    # Build ordered lists of unmatched cmd-occurrence keys for each side
    stn_unmatched_cmds = []
    ds_unmatched_cmds  = []
    for h in only_stn_headers:
        stn_unmatched_cmds.append(stn_map[h])
    for h in only_ds_headers:
        ds_unmatched_cmds.append(ds_map[h])

    # Pair unmatched by cmd-occ keys where both sides have same (cmd, occ)
    stn_cmd_keys = set(stn_cmd.keys())
    ds_cmd_keys  = set(ds_cmd.keys())
    common_cmdocc = [k for k in stn_cmd_keys & ds_cmd_keys
                     if (k not in [stn_map[h] for h in common_by_header])]

    diffs = []
    lines_out = []

    def block_text(lines):
        # Join as-is; you can tweak normalization if needed (e.g., strip trailing CRs)
        return "\n".join(lines).rstrip()

    # 1) Blocks matched by exact header
    for header in common_by_header:
        stn_lines = stn_h[header]
        ds_lines  = ds_h[header]
        if stn_lines != ds_lines:
            diffs.append(header)
            lines_out.append(f"=== DIFF: {header} ===")
            lines_out.append(f"--- STN ({stn_path.name}) ---")
            lines_out.append(block_text(stn_lines) or "<empty>")
            lines_out.append(f"--- dsPIC ({dspic_path.name}) ---")
            lines_out.append(block_text(ds_lines) or "<empty>")
            lines_out.append("")

    # 2) Blocks matched by (command, occurrence) where header didn’t match
    # Do them in file order using stn_cmd (preserves order seen in STN)
    for key, stn_lines in stn_cmd.items():
        # skip ones already compared by header
        if key in [stn_map[h] for h in common_by_header]:
            continue
        if key in ds_cmd:
            ds_lines = ds_cmd[key]
            if stn_lines != ds_lines:
                cmd, occ = key
                diffs.append(f"[{occ}] {cmd}")
                lines_out.append(f"=== DIFF: [{occ}] {cmd} (matched by command+occurrence) ===")
                lines_out.append(f"--- STN ({stn_path.name}) ---")
                lines_out.append(block_text(stn_lines) or "<empty>")
                lines_out.append(f"--- dsPIC ({dspic_path.name}) ---")
                lines_out.append(block_text(ds_lines) or "<empty>")
                lines_out.append("")

    # 3) Report blocks only on one side (no counterpart)
    #    Keep them, since they are meaningful differences in flow
    only_stn_reported = []
    for h in only_stn_headers:
        # skip if its cmd-occurrence was already compared (paired by command+occ)
        if stn_map[h] in ds_cmd:
            continue
        only_stn_reported.append(h)
        lines_out.append(f"=== ONLY IN STN: {h} ===")
        lines_out.append(block_text(stn_h[h]) or "<empty>")
        lines_out.append("")

    only_ds_reported = []
    for h in only_ds_headers:
        if ds_map[h] in stn_cmd:
            continue
        only_ds_reported.append(h)
        lines_out.append(f"=== ONLY IN dsPIC: {h} ===")
        lines_out.append(block_text(ds_h[h]) or "<empty>")
        lines_out.append("")

    if lines_out:
        out_path.write_text("\n".join(lines_out), encoding="utf-8")
        return True, diffs, only_stn_reported, only_ds_reported
    else:
        return False, [], [], []

def main():
    parser = argparse.ArgumentParser(
        description="Compare STN vs dsPIC logs per command block (--- [n] NAME ---) and write only the differences."
    )
    parser.add_argument("stn_folder", help="Folder containing STN logs")
    parser.add_argument("dspic_folder", help="Folder containing dsPIC logs")
    parser.add_argument("-o", "--output", default="diff_output", help="Output folder for per-file diffs")
    parser.add_argument("--ext", default=".txt", help="File extension to match (default: .txt)")
    args = parser.parse_args()

    stn_dir = Path(args.stn_folder)
    ds_dir  = Path(args.dspic_folder)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    stn_files = {p.name: p for p in stn_dir.glob(f"*{args.ext}")}
    ds_files  = {p.name: p for p in ds_dir.glob(f"*{args.ext}")}

    common_names = sorted(set(stn_files) & set(ds_files))
    only_stn = sorted(set(stn_files) - set(ds_files))
    only_ds  = sorted(set(ds_files) - set(stn_files))

    summary = []
    summary.append(f"STN folder : {stn_dir.resolve()}")
    summary.append(f"dsPIC folder: {ds_dir.resolve()}")
    summary.append(f"Output dir : {out_dir.resolve()}")
    summary.append("")
    summary.append(f"Unpaired in STN ({len(only_stn)}): {', '.join(only_stn) if only_stn else '-'}")
    summary.append(f"Unpaired in dsPIC ({len(only_ds)}): {', '.join(only_ds) if only_ds else '-'}")
    summary.append("")
    summary.append(f"Comparing {len(common_names)} paired files...")
    summary.append("")

    created = 0
    for name in common_names:
        stn_path = stn_files[name]
        ds_path  = ds_files[name]
        diff_path = out_dir / f"{Path(name).stem}.diff.txt"

        has_diff, difflist, only_stn_blocks, only_ds_blocks = compare_files(stn_path, ds_path, diff_path)
        if has_diff:
            created += 1
            summary.append(f"[DIFF] {name} -> {diff_path.name} "
                           f"(block diffs: {len(difflist)}, only-in-STN: {len(only_stn_blocks)}, only-in-dsPIC: {len(only_ds_blocks)})")
        else:
            # no differences at block level
            summary.append(f"[SAME] {name} (no block-level differences)")

    summary.append("")
    summary.append(f"Diff files created: {created} / {len(common_names)}")

    (out_dir / "SUMMARY.txt").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))

if __name__ == "__main__":
    main()
