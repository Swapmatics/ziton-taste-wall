#!/usr/bin/env python3
"""
Taste-wall technical contract — build gate.

Fails if any /variants/*.html violates:
  - exactly one <h1>
  - <nav aria-label="Primary"> present
  - every href="#x" has id="x" in document
  - id="contact" lives on <footer> (exactly one)
  - at most one :root block
  - CSS custom props look syntactically valid (esp. colors)
  - no opacity on text-bearing rules (heuristic: opacity in CSS
    associated with text selectors / any opacity < 1 on common text selectors)
  - text-bearing opacity under 1 anywhere in CSS (strict: any `opacity:` < 1
    that appears in the stylesheet — taste wall must use --muted)

Usage:
  python3 scripts/validate_taste_wall.py
  python3 scripts/validate_taste_wall.py --json
Exit code 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Support both Ziton monorepo layout and the public taste-wall repo.
_CANDIDATES = [
    ROOT / "data/clients/_taste-wall/variants",
    ROOT / "variants",
]
VARIANTS = next((p for p in _CANDIDATES if p.is_dir()), _CANDIDATES[0])

HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
RGB = re.compile(r"^rgba?\([^)]+\)$", re.I)
HSL = re.compile(r"^hsla?\([^)]+\)$", re.I)
COLOR_MIX = re.compile(r"^color-mix\([^)]+\)$", re.I)
VAR_REF = re.compile(r"^var\(--[a-zA-Z0-9_-]+(?:,\s*[^)]+)?\)$")
LENGTH = re.compile(
    r"^(\d+(\.\d+)?(px|rem|em|vh|vw|%|ch)|0|clamp\([^)]+\)|calc\([^)]+\)|min\([^)]+\)|max\([^)]+\))$",
    re.I,
)
KEYWORD = re.compile(
    r"^(transparent|currentcolor|inherit|initial|unset|none|solid|auto|normal|bold|"
    r"italic|uppercase|lowercase|center|left|right|flex|grid|block|inline|relative|"
    r"absolute|fixed|sticky|hidden|scroll|visible|wrap|nowrap|column|row|"
    r"space-between|space-around|flex-start|flex-end|baseline|stretch)$",
    re.I,
)
# color-like custom props
COLOR_PROPS = re.compile(r"--(bg|fg|accent|mute|muted|ink|ok|warn|red|gold|leaf|iso|sig|line|steel|copper|navy|glass|frame|lime|incise|note|paper|card|dark|led|amber|teal|rose|haz|blue|mint|wine|yellow|a|b|c)\b", re.I)


@dataclass
class Finding:
    code: str
    detail: str


@dataclass
class Report:
    file: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def extract_style(html: str) -> str:
    m = re.search(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)
    return m.group(1) if m else ""


def count_root_blocks(css: str) -> int:
    return len(re.findall(r"(?:^|})\s*:root\s*\{", css))


def validate_custom_props(css: str) -> list[Finding]:
    out: list[Finding] = []
    for m in re.finditer(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;}{]+)", css):
        name, raw = m.group(1), m.group(2).strip()
        # strip !important
        val = re.sub(r"\s*!important\s*$", "", raw).strip()
        if not val:
            out.append(Finding("bad_token", f"{name}: empty"))
            continue
        # skip complex multi-value for non-color (font stacks etc.)
        if name in {"--display", "--body", "--unit", "--u", "--s", "--g", "--m", "--air", "--rhythm", "--gutter", "--space", "--row", "--col", "--pad", "--gap"} or name.endswith(("unit", "u", "s", "g", "m")):
            continue
        if COLOR_PROPS.search(name) or name in {"--bg", "--fg", "--accent", "--mute", "--muted", "--warn", "--ok"}:
            ok = bool(
                HEX.match(val)
                or RGB.match(val)
                or HSL.match(val)
                or COLOR_MIX.match(val)
                or VAR_REF.match(val)
                or val.lower() in {"transparent", "currentcolor", "inherit"}
            )
            # color-mix can be truncated in our naive regex if nested — allow color-mix( start
            if not ok and val.startswith("color-mix("):
                ok = True
            if not ok:
                out.append(Finding("bad_token", f"{name}:{val}"))
        # catch obvious garble anywhere: space inside hex-like
        if re.search(r"#[0-9a-fA-F]{0,5}\s+[a-zA-Z]", val) or re.search(r"#[0-9a-fA-F]*\s+gener", val):
            out.append(Finding("bad_token", f"{name}:{val} (garbled)"))
    return out


def _opacity_hits(blob: str, *, ignore_contract_comment: bool = True) -> list[Finding]:
    out: list[Finding] = []
    for m in re.finditer(r"opacity\s*:\s*([^;\"'\s}{]+)", blob, re.I):
        raw = m.group(1).strip().rstrip(";")
        if ignore_contract_comment:
            start = max(0, m.start() - 48)
            if "never opacity" in blob[start : m.start()]:
                continue
        try:
            if raw.endswith("%"):
                v = float(raw[:-1]) / 100.0
            else:
                v = float(raw)
        except ValueError:
            continue
        if v < 1.0:
            out.append(Finding("text_opacity", f"opacity:{raw}"))
    return out


def text_opacity_findings(css: str) -> list[Finding]:
    """Flag opacity < 1 inside <style> blocks."""
    return _opacity_hits(css)


def inline_opacity_findings(html: str) -> list[Finding]:
    """Flag opacity < 1 in inline style= attributes (outside <style>)."""
    out: list[Finding] = []
    html_wo = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    for m in re.finditer(r'''style\s*=\s*(["'])(.*?)\1''', html_wo, re.I | re.S):
        out.extend(_opacity_hits(m.group(2), ignore_contract_comment=False))
    return out


def check_file(path: Path) -> Report:
    html = path.read_text(encoding="utf-8")
    css = extract_style(html)
    r = Report(file=path.name)

    # h1 exactly one
    h1s = re.findall(r"<h1\b", html, re.I)
    if len(h1s) != 1:
        r.findings.append(Finding("h1_count", f"found {len(h1s)}"))

    # nav landmark
    if not re.search(r"<nav\b[^>]*aria-label\s*=\s*[\"']Primary[\"']", html, re.I):
        if not re.search(r"<nav\b", html, re.I):
            r.findings.append(Finding("nav_missing", "no <nav>"))
        else:
            r.findings.append(Finding("nav_aria", "nav lacks aria-label=Primary"))

    # footer id=contact
    footers = re.findall(r"<footer\b[^>]*>", html, re.I)
    contact_on_footer = bool(re.search(r"<footer\b[^>]*\bid\s*=\s*[\"']contact[\"']", html, re.I))
    if not contact_on_footer:
        r.findings.append(Finding("contact_footer", "id=contact not on <footer>"))
    # contact id should appear once
    contact_ids = len(re.findall(r'\bid\s*=\s*["\']contact["\']', html, re.I))
    if contact_ids != 1:
        r.findings.append(Finding("contact_count", f"id=contact appears {contact_ids} times"))

    # href="#x" must have id
    anchors = re.findall(r'<a\b[^>]*href\s*=\s*["\']#([^"\']+)["\']', html, re.I)
    for a in sorted(set(anchors)):
        if not re.search(rf'\bid\s*=\s*["\']{re.escape(a)}["\']', html, re.I):
            r.findings.append(Finding("broken_hash", f"#{a} missing id"))

    # --muted / --mute required
    if not re.search(r"--mute[d]?\s*:", css):
        r.findings.append(Finding("no_muted_token", "missing --mute or --muted in :root"))

    # :root count
    roots = count_root_blocks(css)
    if roots != 1:
        r.findings.append(Finding("root_count", f":root blocks={roots}"))

    r.findings.extend(validate_custom_props(css))
    r.findings.extend(text_opacity_findings(css))
    r.findings.extend(inline_opacity_findings(html))

    # lexical nav label ↔ id soft checks (flag only when clearly wrong patterns)
    # Practice -> Private chambers style: check known bad pairs via link text
    for m in re.finditer(
        r'<a\b[^>]*href\s*=\s*["\']#([^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        re.I | re.S,
    ):
        target, label = m.group(1), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip().lower()
        # find element with that id and its inner text ~120 chars
        im = re.search(
            rf'<([a-z0-9]+)([^>]*\bid\s*=\s*["\']{re.escape(target)}["\'][^>]*)>(.*?)</\1>',
            html,
            re.I | re.S,
        )
        if not im:
            # self-closing or id on void — try attribute-only
            continue
        tag = im.group(1).lower()
        inner = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", im.group(3))).strip().lower()
        # id must not live on span/strong/time alone for section labels
        if tag in {"span", "strong", "time", "i", "em"} and target not in {"contact"}:
            r.findings.append(
                Finding("hash_host", f"#{target} on <{tag}> for label '{label}'")
            )
        # specific known bad: practice → private chambers
        if "practice" in label and "private chamber" in inner:
            r.findings.append(
                Finding("hash_lex", f"'{label}' → #{target} content '{inner[:60]}'")
            )

    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--path", type=Path, default=VARIANTS)
    args = ap.parse_args()

    files = sorted(args.path.glob("*.html"))
    reports = [check_file(p) for p in files]
    failed = [r for r in reports if not r.ok]

    if args.json:
        print(
            json.dumps(
                {
                    "total": len(reports),
                    "failed": len(failed),
                    "reports": [
                        {
                            "file": r.file,
                            "ok": r.ok,
                            "findings": [{"code": f.code, "detail": f.detail} for f in r.findings],
                        }
                        for r in reports
                    ],
                },
                indent=2,
            )
        )
    else:
        print(f"Taste wall contract — {len(reports)} files, {len(failed)} failing\n")
        print(f"{'FILE':<32} {'STATUS':<6} FINDINGS")
        print("-" * 88)
        for r in reports:
            if r.ok:
                print(f"{r.file:<32} PASS")
            else:
                summary = "; ".join(f"{f.code}:{f.detail}" for f in r.findings[:4])
                more = f" (+{len(r.findings)-4})" if len(r.findings) > 4 else ""
                print(f"{r.file:<32} FAIL   {summary}{more}")
        print()
        # aggregate codes
        from collections import Counter

        c: Counter[str] = Counter()
        for r in failed:
            for f in r.findings:
                c[f.code] += 1
        if c:
            print("By code:")
            for k, v in c.most_common():
                print(f"  {k}: {v}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
