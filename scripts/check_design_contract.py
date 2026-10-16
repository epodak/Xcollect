"""Minimal standard-library checks for committed Xcollect product/design context.

This checks documentation shape, not visual quality or third-party tool installation.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "PRODUCT.md": ("## Platform and audience", "## The product problem to solve first", "## Evidence versus assumptions"),
    "DESIGN.md": ("version: alpha", "## Overview", "## Colors", "## Typography", "## Layout", "## Components", "## Do's and Don'ts"),
    "docs/design/READING_EXPERIENCE.md": ("## The diagnosis", "## Install the design skill for development", "## Every design iteration"),
}

def main() -> int:
    errors = []
    for relative, headings in REQUIRED.items():
        file = ROOT / relative
        if not file.is_file():
            errors.append(f"missing: {relative}")
            continue
        text = file.read_text(encoding="utf-8")
        for heading in headings:
            if heading not in text:
                errors.append(f"{relative}: missing {heading!r}")
    design = ROOT / "DESIGN.md"
    if design.is_file() and not design.read_text(encoding="utf-8").startswith("---\n"):
        errors.append("DESIGN.md: expected Stitch-compatible YAML frontmatter")
    if errors:
        print("Design contract FAILED:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print("Design contract OK (documentation structure only; no visual verification)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
