"""Compile a LaTeX resume (a .tex file or an Overleaf project .zip) to PDF with pdflatex.

The source is untrusted input, so every compile runs locked down: a fresh temporary folder, no shell escape,
kpathsea in paranoid mode (no absolute paths, no "..", no dotfiles — a resume can't \\input /etc/passwd), a time
limit and output-size caps. Results are cached by content hash, so re-rendering the same source is instant.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import OrderedDict
from pathlib import Path, PurePosixPath

MAX_FILES = 200
MAX_UNPACKED = 25 * 1024 * 1024
TIMEOUT_S = 45
_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_CACHE_MAX = 24


class LatexError(ValueError):
    """The source didn't compile; the message says why in plain words."""


def available() -> bool:
    return shutil.which("pdflatex") is not None


def is_zip(data: bytes) -> bool:
    return data[:4] == b"PK\x03\x04"


def load_project(data: bytes) -> tuple[dict[str, bytes], str]:
    """({relative path: bytes}, main .tex path). A plain .tex is a one-file project."""
    if not is_zip(data):
        return {"main.tex": data}, "main.tex"
    files: dict[str, bytes] = {}
    total = 0
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise LatexError("This .zip file can't be opened.")
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise LatexError(f"The project has more than {MAX_FILES} files.")
    for info in infos:
        name = PurePosixPath(info.filename.replace("\\", "/"))
        if name.is_absolute() or ".." in name.parts or any(p.startswith(".") for p in name.parts) or "__MACOSX" in name.parts:
            continue
        total += info.file_size
        if total > MAX_UNPACKED:
            raise LatexError("The project is too large (over 25 MB unpacked).")
        files[str(name)] = z.read(info)
    # Overleaf zips may put everything in one top folder: strip it
    tops = {p.split("/", 1)[0] for p in files}
    if len(tops) == 1 and all("/" in p for p in files):
        top = next(iter(tops)) + "/"
        files = {p[len(top):]: b for p, b in files.items()}
    mains = [p for p, b in files.items() if p.endswith(".tex") and b"\\documentclass" in b and b"\\begin{document}" in b]
    if not mains:
        raise LatexError("No main .tex file (with \\documentclass and \\begin{document}) was found in the .zip.")
    mains.sort(key=lambda p: (p.count("/"), Path(p).stem.lower() not in ("main", "resume", "cv"), len(p)))
    return files, mains[0]


def _first_error(log: str) -> str:
    # -file-line-error-style: "./main.tex:9: LaTeX Error: File `x.sty' not found."
    m = re.search(r"LaTeX Error: (File `[^']+' not found)", log)
    if m:
        return m.group(1)
    m = re.search(r"^(?:\./)?[^:\n]*\.(?:tex|cls|sty):(\d+): (?!Emergency stop)(.+)$", log, re.M)
    if m:
        return f"{m.group(2).strip().rstrip('.')} (line {m.group(1)})"
    m = re.search(r"^! (.+)$", log, re.M)
    return m.group(1).strip() if m else "pdflatex stopped without a clear error"


def missing_package(msg: str) -> str:
    m = re.search(r"File `?([^'`\s]+?)\.(sty|cls)'? not found", msg)
    return m.group(1) if m else ""


def compile_pdf(files: dict[str, bytes], main: str) -> bytes:
    """Compile and return the PDF bytes. Raises LatexError with the first LaTeX error."""
    if not available():
        raise LatexError("LaTeX isn't installed on this server.")
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(p.encode() + b"\0" + files[p] + b"\0")
    key = h.hexdigest() + ":" + main
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    with tempfile.TemporaryDirectory(prefix="jp-tex-") as tmp:
        root = Path(tmp)
        for p, b in files.items():
            f = root / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "TEXMFVAR": str(root / ".texmf-var"),
               "openin_any": "p", "openout_any": "p", "shell_escape": "f", "max_print_line": "1000"}
        workdir = (root / main).parent
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "-file-line-error-style",
               Path(main).name]
        log = ""
        for _ in range(2):  # a second pass only when LaTeX asks for one (page refs, lastpage)
            try:
                r = subprocess.run(cmd, cwd=workdir, env=env, capture_output=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                raise LatexError(f"LaTeX took longer than {TIMEOUT_S} seconds.")
            logf = workdir / (Path(main).stem + ".log")
            log = logf.read_text("latin-1", errors="replace") if logf.exists() else r.stdout.decode("latin-1", "replace")
            if r.returncode != 0:
                raise LatexError(_first_error(log))
            if "Rerun to get" not in log and "rerunfilecheck" not in log:
                break
        pdf = workdir / (Path(main).stem + ".pdf")
        if not pdf.exists():
            raise LatexError(_first_error(log))
        out = pdf.read_bytes()
    _CACHE[key] = out
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return out


def compile_source(data: bytes) -> bytes:
    files, main = load_project(data)
    return compile_pdf(files, main)
