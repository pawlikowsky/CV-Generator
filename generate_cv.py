#!/usr/bin/env python3
"""
CV Generator
============
Converts a structured Markdown CV file into a styled HTML document,
optionally exporting it to PDF via WeasyPrint.

Usage:
    python generate_cv.py cv-sample.md
    python generate_cv.py cv-sample.md -o output.html
    python generate_cv.py cv-sample.md --pdf
    python generate_cv.py cv-sample.md -o my-cv.html --pdf

Markdown schema:
    See cv-sample.md for the expected format.
"""

import argparse
from pathlib import Path
import re
import sys

from jinja2 import Environment, FileSystemLoader
import markdown as md_lib
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class ExperienceItem(BaseModel):
    position: str
    company: str
    period: str = ""
    location: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    stack: str = ""


class EducationItem(BaseModel):
    degree: str
    institution: str
    period: str = ""


class SkillCategory(BaseModel):
    category: str
    items: str


class CVData(BaseModel):
    name: str = ""
    title: str = ""
    contacts: list[str] = Field(default_factory=list)
    summary: str = ""
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    skills: list[SkillCategory] = Field(default_factory=list)
    languages: list[dict] = Field(default_factory=list)
    certifications: list[dict] = Field(default_factory=list)
    footer: str = ""
    llm_prompt: str = ""
    lang: str = "en"


# ---------------------------------------------------------------------------
# Inline markdown → HTML helper (bold, italic, links, code)
# ---------------------------------------------------------------------------


def inline_md(text: str) -> str:
    """Convert inline markdown (bold, italic, links, code) to HTML."""
    # Convert only inline elements - wrap result is a <p>, strip those tags
    result = md_lib.markdown(text)
    result = re.sub(r"^<p>(.*)</p>$", r"\1", result.strip(), flags=re.DOTALL)
    return result


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Canonical section name mapping
_SECTION_MAP = {
    "summary": "summary",
    "professional profile": "summary",
    "profile": "summary",
    "about": "summary",
    "experience": "experience",
    "professional experience": "experience",
    "work experience": "experience",
    "education": "education",
    "skills": "skills",
    "key skills": "skills",
    "technical skills": "skills",
    "languages": "languages",
    "certifications": "certifications",
    "certificates": "certifications",
    "footer": "footer",
    "gdpr": "footer",
    "consent": "footer",
    "llm": "llm_prompt",
    "ai": "llm_prompt",
    "ai prompt": "llm_prompt",
    "llm prompt": "llm_prompt",
}


def _normalize_section(raw: str) -> str:
    return _SECTION_MAP.get(raw.strip().lower(), raw.strip().lower())


def _parse_sub_header(sub_header: str) -> tuple[str, str, str]:
    """
    Parse '### Position | Company (Location)' or '### Position @ Company'
    Returns (primary, secondary, location)
    """
    location = ""
    if " | " in sub_header:
        primary, rest = sub_header.split(" | ", 1)
        loc_match = re.search(r"\(([^)]+)\)\s*$", rest)
        if loc_match:
            location = loc_match.group(1)
            rest = rest[: loc_match.start()].strip()
        return primary.strip(), rest.strip(), location
    elif " @ " in sub_header:
        primary, rest = sub_header.split(" @ ", 1)
        return primary.strip(), rest.strip(), location
    return sub_header.strip(), "", location


def parse_cv_markdown(content: str) -> CVData:
    cv = CVData()
    lines = content.splitlines()

    section: str | None = None
    current_exp: ExperienceItem | None = None
    current_edu: EducationItem | None = None
    summary_lines: list[str] = []

    def _flush_exp():
        nonlocal current_exp
        if current_exp:
            cv.experience.append(current_exp)
            current_exp = None

    def _flush_edu():
        nonlocal current_edu
        if current_edu:
            cv.education.append(current_edu)
            current_edu = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── H1: Name ────────────────────────────────────────────────────────
        if stripped.startswith("# ") and not cv.name:
            cv.name = stripped[2:].strip()
            i += 1
            # Look ahead for optional title + contacts
            while i < len(lines):
                peek = lines[i].strip()
                if peek == "---" or peek.startswith("#"):
                    break
                if not peek:
                    i += 1
                    continue  # skip blank lines within the header block
                if " | " in peek:
                    # Contacts line
                    cv.contacts = [c.strip() for c in peek.split(" | ")]
                    i += 1
                elif not cv.title:
                    cv.title = peek
                    i += 1
                else:
                    break
            continue

        # ── H2: Section change ───────────────────────────────────────────────
        if stripped.startswith("## "):
            _flush_exp()
            _flush_edu()
            # Commit buffered summary
            if summary_lines:
                cv.summary = inline_md(" ".join(summary_lines))
                summary_lines = []
            section = _normalize_section(stripped[3:])
            i += 1
            continue

        # ── H3: Sub-item (experience / education) ───────────────────────────
        if stripped.startswith("### "):
            _flush_exp()
            _flush_edu()
            sub_header = stripped[4:].strip()

            if section == "experience":
                pos, company, loc = _parse_sub_header(sub_header)
                current_exp = ExperienceItem(position=pos, company=company, location=loc)
            elif section == "education":
                degree, institution, _ = _parse_sub_header(sub_header)
                current_edu = EducationItem(degree=degree, institution=institution)
            i += 1
            continue

        # ── Horizontal rule ──────────────────────────────────────────────────
        if stripped in ("---", "***", "___"):
            i += 1
            continue

        # ── Section-specific content ─────────────────────────────────────────

        if section == "experience" and current_exp is not None:
            # Date line: **Period**
            date_match = re.match(r"^\*\*([^*]+)\*\*\s*$", stripped)
            if date_match and not current_exp.period:
                current_exp.period = date_match.group(1)

            # Stack line: **Stack:** ...
            elif re.match(r"^\*\*Stack:\*\*\s*(.+)", stripped):
                m = re.match(r"^\*\*Stack:\*\*\s*(.+)", stripped)
                current_exp.stack = m.group(1).strip()

            # Responsibility bullet
            elif stripped.startswith("- ") or stripped.startswith("* "):
                current_exp.responsibilities.append(inline_md(stripped[2:].strip()))

        elif section == "education" and current_edu is not None:
            date_match = re.match(r"^\*\*([^*]+)\*\*\s*$", stripped)
            if date_match and not current_edu.period:
                current_edu.period = date_match.group(1)

        elif section == "summary":
            if stripped:
                summary_lines.append(stripped)

        elif section == "skills":
            # - **Category:** items  OR  * **Category:** items
            m = re.match(r"^[-*]\s+\*\*([^*:]+):\*\*\s*(.+)", stripped)
            if m:
                cv.skills.append(
                    SkillCategory(category=m.group(1).strip(), items=m.group(2).strip())
                )

        elif section == "languages":
            # - **Language** — Level
            m = re.match(r"^[-*]\s+\*\*([^*]+)\*\*\s*[—–\-]+\s*(.+)", stripped)
            if m:
                cv.languages.append({"language": m.group(1).strip(), "level": m.group(2).strip()})

        elif section == "certifications":
            # - **Cert name** — Issuer, Year
            m = re.match(r"^[-*]\s+\*\*([^*]+)\*\*\s*[—–\-]+\s*(.+)", stripped)
            if m:
                cv.certifications.append({"name": m.group(1).strip(), "issuer": m.group(2).strip()})
            # Plain bullet without bold
            elif stripped.startswith("- ") or stripped.startswith("* "):
                cv.certifications.append({"name": stripped[2:].strip(), "issuer": ""})

        elif section == "footer":
            if stripped:
                # Strip surrounding asterisks used for italic/bold wrapping
                cv.footer += (" " if cv.footer else "") + stripped.strip("*").strip()

        elif section == "llm_prompt":
            if stripped:
                cv.llm_prompt += (" " if cv.llm_prompt else "") + stripped.strip("*").strip()

        i += 1

    # Final flush
    _flush_exp()
    _flush_edu()
    if summary_lines:
        cv.summary = inline_md(" ".join(summary_lines))

    return cv


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE = "cv_template.jinja2"
DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"


def render_html(cv: CVData, template_dir: Path, template_name: str = DEFAULT_TEMPLATE) -> str:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,  # We handle escaping manually where needed
    )
    template = env.get_template(template_name)
    return template.render(cv=cv)


# ---------------------------------------------------------------------------
# PDF export (optional - requires WeasyPrint)
# ---------------------------------------------------------------------------


def export_pdf(html_content: str, output_path: Path) -> None:
    try:
        from weasyprint import HTML
    except ImportError:
        print(
            "ERROR: WeasyPrint is not installed.\nInstall it with:  pip install weasyprint",
            file=sys.stderr,
        )
        sys.exit(1)

    HTML(string=html_content).write_pdf(str(output_path))
    print(f"PDF saved → {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate a styled HTML (and optionally PDF) CV from a Markdown file."
    )
    p.add_argument("input", help="Path to the input Markdown (.md) CV file")
    p.add_argument(
        "-o",
        "--output",
        help="Output HTML file path (default: output/<input-name>.html)",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated files (default: output/ next to this script)",
    )
    p.add_argument(
        "--pdf",
        action="store_true",
        help="Also export a PDF alongside the HTML (requires WeasyPrint)",
    )
    p.add_argument(
        "--template-dir",
        default=None,
        help="Directory containing the Jinja2 template (default: templates/ next to this script)",
    )
    p.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        help=(
            "Jinja2 template filename to use (default: cv_template.jinja2).\n"
            "Available built-in templates:\n"
            "  cv_template.jinja2       — clean single-column, white background\n"
            "  cv_template_warm.jinja2  — two-column sidebar, warm cream palette"
        ),
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    template_dir = Path(args.template_dir).resolve() if args.template_dir else DEFAULT_TEMPLATE_DIR
    template_name = args.template

    # Validate template exists
    template_path = template_dir / template_name
    if not template_path.exists():
        print(f"ERROR: Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output directory and path
    output_dir = Path(args.output_dir).resolve() if args.output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_html = Path(args.output).resolve()
    else:
        output_html = output_dir / (input_path.stem + ".html")

    # Parse
    content = input_path.read_text(encoding="utf-8")
    cv_data = parse_cv_markdown(content)

    if not cv_data.name:
        print("WARNING: Could not detect a name (H1 heading) in the file.", file=sys.stderr)

    # Render
    html = render_html(cv_data, template_dir, template_name)

    # Write HTML
    output_html.write_text(html, encoding="utf-8")
    print(f"HTML saved → {output_html}")

    # Optional PDF
    if args.pdf:
        output_pdf = output_html.with_suffix(".pdf")
        export_pdf(html, output_pdf)


if __name__ == "__main__":
    main()
