import zipfile, pathlib, sys
root = pathlib.Path(r"C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab")
out = pathlib.Path(r"C:\Users\qq165\Documents\deepseek-harness\default-workspace\_gandan_snapshots\v1_d1_rules_green.zip")
skip_dirs = {".venv", "__pycache__", ".pytest_cache"}
n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob("*")):
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.is_file() and p.suffix != ".jsonl":
            z.write(p, p.relative_to(root))
            n += 1
print("files", n, "size_MB", round(out.stat().st_size/1e6, 2))
