#!/usr/bin/env python3
"""
Apply taste-wall technical contract fixes across all variants.

Mutates HTML in place under data/clients/_taste-wall/variants/.
Run validate_taste_wall.py afterward — must exit 0.
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "data/clients/_taste-wall/variants",
    Path(__file__).resolve().parents[1] / "variants",
]
VARIANTS = next((p for p in _CANDIDATES if p.is_dir()), _CANDIDATES[0])

# Approximate relative luminance helpers for --muted derivation
def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore


def rel_lum(rgb: tuple[float, float, float]) -> float:
    def f(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (f(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    l1, l2 = rel_lum(a), rel_lum(b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(c * 255)))):02x}" for c in rgb)


def muted_for(bg_hex: str, fg_hex: str) -> str:
    """Pick a muted fg that keeps >=4.5:1 vs bg, biased toward fg hue."""
    try:
        bg, fg = hex_to_rgb(bg_hex), hex_to_rgb(fg_hex)
    except Exception:
        return "#666666"
    # blend fg toward bg until just above 4.5, then back off one step
    best = fg_hex if contrast(fg, bg) >= 4.5 else "#666666"
    for t in [i / 40 for i in range(0, 41)]:
        blended = tuple(fg[i] * (1 - t) + bg[i] * t for i in range(3))
        if contrast(blended, bg) >= 4.5:
            best = rgb_to_hex(blended)  # type: ignore
        else:
            break
    # Prefer museum-label style mid gray when bg is light
    if rel_lum(bg) > 0.5:
        candidates = ["#666666", "#5c5c5c", "#4a4a4a", "#3d3d3d", best]
    else:
        candidates = ["#a0a0a0", "#b0b0b0", "#c0c0c0", "#9aa3ad", best]
    for c in candidates:
        try:
            if contrast(hex_to_rgb(c), bg) >= 4.5:
                return c
        except Exception:
            continue
    return best


def extract_root_colors(css: str) -> tuple[str, str]:
    bg = fg = None
    for m in re.finditer(r"--bg\s*:\s*(#[0-9a-fA-F]{3,8})", css):
        bg = m.group(1)
    for m in re.finditer(r"--fg\s*:\s*(#[0-9a-fA-F]{3,8})", css):
        fg = m.group(1)
    # also common aliases
    if not fg:
        for key in ("--ink", "--paper"):
            m = re.search(rf"{key}\s*:\s*(#[0-9a-fA-F]{{3,8}})", css)
            if m and key == "--ink":
                fg = m.group(1)
    return bg or "#ffffff", fg or "#111111"


def collapse_root_and_tokens(css: str) -> str:
    """Ensure single :root; inject --muted; strip garbled tokens; drop opacity."""
    bg, fg = extract_root_colors(css)
    mute = muted_for(bg, fg)

    # Fix known garbles
    css = re.sub(r"--warn\s*:\s*#f0c\s+gener\s*;?", "", css)
    css = re.sub(r":root\s*\{\s*--warn\s*:\s*#f0c84a\s*;\s*\}", "", css)

    # Remove ALL opacity declarations (contract: use --muted / alpha colors)
    # Handles both `opacity:.55;` and minified `opacity:.55}`
    css = re.sub(r"opacity\s*:\s*[^;}{]+;?\s*", "", css)

    # Merge multiple :root into one — extract all decls from every :root
    roots = list(re.finditer(r":root\s*\{([^{}]*)\}", css))
    decls: list[str] = []
    seen_keys: set[str] = set()
    for m in roots:
        body = m.group(1)
        for part in body.split(";"):
            part = part.strip()
            if not part or ":" not in part:
                continue
            key = part.split(":", 1)[0].strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            decls.append(part)
        css = css.replace(m.group(0), "/*__ROOT__*/", 1)

    # ensure muted
    if not any(d.startswith("--mute") for d in decls):
        decls.append(f"--muted: {mute}")
        decls.append(f"--mute: {mute}")
    else:
        # normalize alias
        if not any(d.startswith("--muted") for d in decls):
            decls.append(f"--muted: {mute}")
        if not any(d.startswith("--mute:") for d in decls) and not any(
            d.startswith("--mute ") for d in decls
        ):
            # --mute may exist as --mute:
            if not any(re.match(r"--mute\s*:", d) for d in decls):
                decls.append(f"--mute: var(--muted)")

    root_block = ":root {\n  " + ";\n  ".join(decls) + ";\n}\n"
    # replace first placeholder; remove rest
    if "/*__ROOT__*/" in css:
        css = css.replace("/*__ROOT__*/", root_block, 1)
        css = css.replace("/*__ROOT__*/", "")
    else:
        css = root_block + css

    # Map common de-emphasis that relied on opacity — add muted color rules
    # Ensure a, .tag, .sub, footer defaults that used opacity get color:var(--muted)
    extras = """
/* contract: de-emphasis via --muted, never opacity */
.tag, .meta, .eyebrow, .kicker, .deck, .chip, .num, .sz, .artist, .byline, .period,
.coords, .status, .live, .chap, .hole + .num, footer, footer.contact, .addr {
  color: var(--muted);
}
nav a, .nav a, .desk a, .links a, .tabs a:not(.focus):not(.keep):not(.p):not(.on),
.topnav a, .corners nav a {
  color: var(--muted);
}
nav a:hover, .nav a:hover { color: var(--fg); }
"""
    if "contract: de-emphasis" not in css:
        css += extras

    # Fix chess board
    if ".board i:nth-child" in css and "tr:nth-child" in css:
        css = re.sub(
            r"\.board i:nth-child\(odd\)\{[^}]+\}",
            "",
            css,
        )
        css = re.sub(
            r"\.board i:nth-child\(even\)\{[^}]+\}",
            "",
            css,
        )
        css = re.sub(
            r"\.board tr:nth-child\(even\) i:nth-child\(odd\)\{[^}]+\}",
            "",
            css,
        )
        css = re.sub(r"/\*\s*simpler checker via nth\s*\*/", "", css)
        chess_fix = """
/* true checker: 8-col grid, row-aware (16n periods) */
.board i{background:#f7f1e6}
.board i:nth-child(16n+1),
.board i:nth-child(16n+3),
.board i:nth-child(16n+5),
.board i:nth-child(16n+7),
.board i:nth-child(16n+10),
.board i:nth-child(16n+12),
.board i:nth-child(16n+14),
.board i:nth-child(16n+16){background:#c4b49a}
"""
        css += chess_fix

    return css


def ensure_nav(html: str) -> str:
    """Guarantee <nav aria-label="Primary"> exists; wrap bare header links if needed."""
    if re.search(r"<nav\b[^>]*aria-label\s*=\s*[\"']Primary[\"']", html, re.I):
        return html
    # upgrade existing nav
    if re.search(r"<nav\b", html, re.I):
        html = re.sub(
            r"<nav\b([^>]*)>",
            lambda m: (
                m.group(0)
                if "aria-label" in m.group(0).lower()
                else f'<nav aria-label="Primary"{m.group(1)}>'
            ),
            html,
            count=1,
            flags=re.I,
        )
        # if still missing (aria on wrong), force
        if not re.search(r"<nav\b[^>]*aria-label\s*=\s*[\"']Primary[\"']", html, re.I):
            html = re.sub(r"<nav\b", '<nav aria-label="Primary"', html, count=1, flags=re.I)
        return html

    # Cases: header.nav with bare <a>, or .top with <a>, or ul without nav
    # Wrap first group of sibling <a> in header
    def wrap_header_links(h: str) -> str:
        # pattern: <header...>...brand...</div> then bare anchors
        m = re.search(
            r"(<(?:header|div)[^>]*class=\"[^\"]*\bnav\b[^\"]*\"[^>]*>)(.*?)(</(?:header|div)>)",
            h,
            re.S | re.I,
        )
        if not m:
            # heritage-stair: header.nav with brand + bare anchors as children of header.nav
            m = re.search(r"(<header class=\"nav\">)(.*?)(</header>)", h, re.S)
        if m:
            inner = m.group(2)
            if "<nav" in inner.lower():
                return h
            # pull anchors out and wrap
            anchors = re.findall(r"<a\b[^>]*>.*?</a>", inner, re.S | re.I)
            if anchors:
                cleaned = inner
                for a in anchors:
                    cleaned = cleaned.replace(a, "", 1)
                wrapped = cleaned + "<nav aria-label=\"Primary\">" + "".join(anchors) + "</nav>"
                return h[: m.start()] + m.group(1) + wrapped + m.group(3) + h[m.end() :]
        return h

    html2 = wrap_header_links(html)
    if re.search(r"<nav\b", html2, re.I):
        return ensure_nav(html2)  # add aria

    # last resort: inject empty primary nav before first section with contact link
    inject = '<nav aria-label="Primary"><a href="#contact">Contact</a></nav>\n'
    html2 = re.sub(r"(</header>)", r"\1\n" + inject, html, count=1, flags=re.I)
    if "<nav" not in html2.lower():
        html2 = re.sub(r"<body>", "<body>\n" + inject, html, count=1, flags=re.I)
    return html2


def ensure_contact_footer(html: str) -> str:
    """id=contact on a single <footer>; migrate leftover contact ids."""
    # remove id=contact from non-footer
    def strip_bad_contact(m: re.Match) -> str:
        tag = m.group(1)
        attrs = m.group(2)
        if tag.lower() == "footer":
            return m.group(0)
        attrs2 = re.sub(r"\s*id\s*=\s*[\"']contact[\"']", "", attrs, flags=re.I)
        return f"<{tag}{attrs2}>"

    html = re.sub(r"<([a-zA-Z0-9]+)([^>]*\bid\s*=\s*[\"']contact[\"'][^>]*)>", strip_bad_contact, html)

    if re.search(r"<footer\b[^>]*\bid\s*=\s*[\"']contact[\"']", html, re.I):
        return html

    if re.search(r"<footer\b", html, re.I):
        html = re.sub(r"<footer\b([^>]*)>", r'<footer id="contact"\1>', html, count=1, flags=re.I)
        # avoid duplicate id if somehow
        return html

    # create footer
    html = re.sub(
        r"</body>",
        '<footer id="contact">Partner intake · contact desk</footer>\n</body>',
        html,
        count=1,
        flags=re.I,
    )
    return html


def fix_hash_hosts(html: str) -> str:
    """Move section ids off spans onto wrapping footers/sections where possible."""
    # Promote <span id="x">text</span> inside footer to data or sibling section
    # For practice/collection/stacks/work/canons/city — give them a <section id> before footer
    promotions = {
        "practice": "Practice areas",
        "collection": "Collection desk",
        "stacks": "Stacks",
        "work": "Work",
        "canons": "Canons",
        "city": "City practice",
        "families": "Families",
        "stewardship": "Stewardship",
        "bond": "Bond work",
        "land": "Land",
        "edition": "Edition",
        "libel": "Libel",
        "casualty": "Casualty",
        "spectrum": "Spectrum",
        "license": "License",
        "mobility": "Mobility",
        "credits": "Credits",
        "notes": "Notes",
        "weights": "Weights",
        "ops": "Ops",
        "alerts": "Alerts",
        "policy": "Policy",
        "matters": "Matters",
        "items": "Items",
        "regions": "Regions",
        "permits": "Permits",
        "disputes": "Disputes",
        "flights": "Board",
        "q": "Quarters",
        "signal": "Signal",
        "forecast": "Forecast",
        "line": "Line",
        "people": "People",
    }

    # Fix inscription practice lex: span with Private chambers
    html = re.sub(
        r'<span id="practice">Private chambers</span>\s*·\s*by introduction',
        'by introduction',
        html,
    )
    if 'id="practice"' not in html and 'href="#practice"' in html:
        html = re.sub(
            r'(<footer[^>]*>)',
            r'<section id="practice" aria-label="Practice"><h2>Practice</h2><p>Private chambers for trusts and estates continuity.</p></section>\n\1',
            html,
            count=1,
            flags=re.I,
        )

    # Remove dead #people links from nav (or add people section)
    if 'href="#people"' in html and not re.search(r'id="people"', html):
        html = re.sub(
            r'(<footer[^>]*>)',
            r'<section id="people" aria-label="People"><h2>People</h2><p>Partners available by introduction.</p></section>\n\1',
            html,
            count=1,
            flags=re.I,
        )

    # Lift id off span onto a section when span sits in footer
    for sid, title in promotions.items():
        pat = re.compile(
            rf'<span([^>]*)\bid\s*=\s*[\"\']{sid}[\"\']([^>]*)>(.*?)</span>',
            re.I | re.S,
        )
        m = pat.search(html)
        if not m:
            continue
        # remove id from span
        html = pat.sub(rf"<span\1\2>{m.group(3)}</span>", html, count=1)
        if not re.search(rf'id\s*=\s*[\"\']{sid}[\"\']', html):
            block = f'<section id="{sid}" aria-label="{title}"><h2>{title}</h2><p>{re.sub(r"<[^>]+>", "", m.group(3)).strip()}</p></section>\n'
            if re.search(r"<footer\b", html, re.I):
                html = re.sub(r"(<footer\b)", block + r"\1", html, count=1, flags=re.I)
            else:
                html = html.replace("</body>", block + "</body>")

    return html


def fix_type_specimen(html: str, name: str) -> str:
    if "39-type-specimen" not in name:
        return html
    # Convert display row Aa span into h1
    html = re.sub(
        r'(<div class="row display">\s*<span class="sz">72</span>\s*)<span class="Aa">Authority</span>',
        r'\1<h1 class="Aa">Authority</h1>',
        html,
    )
    if "<h1" not in html:
        html = re.sub(
            r"(<section class=\"sheet\"[^>]*>)",
            r'\1\n  <h1 class="Aa">Authority</h1>',
            html,
            count=1,
        )
    return html


def fix_control_room(html: str, name: str) -> str:
    if "40-control-room" not in name:
        return html
    html = html.replace("--warn:#f0c gener;", "--warn:#f0c84a;")
    html = re.sub(r":root\{--warn:#f0c84a\}\s*", "", html)
    # collapse will handle dual root
    return html


def add_font_preload(html: str) -> str:
    """Preload first Google family as style; keep CSS link; add preload for CSS."""
    if 'rel="preload"' in html and "as=\"style\"" in html:
        return html
    m = re.search(
        r'<link href="(https://fonts\.googleapis\.com/css2\?[^"]+)" rel="stylesheet"\s*/?>',
        html,
    )
    if not m:
        return html
    href = m.group(0)
    url = m.group(1)
    preload = f'<link rel="preload" as="style" href="{url}" />\n'
    if "rel=\"preload\" as=\"style\"" not in html:
        html = html.replace(href, preload + href)
    return html


def apply_css(html: str) -> str:
    m = re.search(r"(<style[^>]*>)(.*?)(</style>)", html, re.S | re.I)
    if not m:
        return html
    new_css = collapse_root_and_tokens(m.group(2))
    return html[: m.start()] + m.group(1) + new_css + m.group(3) + html[m.end() :]


def strip_inline_opacity(html: str) -> str:
    html = re.sub(
        r"""(style\s*=\s*["'][^"']*?)opacity\s*:\s*[^;"']+\s*;?\s*""",
        r"\1",
        html,
        flags=re.I,
    )
    html = re.sub(r"""\sstyle\s*=\s*["']\s*["']""", "", html)
    return html


def fix_file(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    name = path.name
    html = fix_control_room(html, name)
    html = apply_css(html)
    html = ensure_nav(html)
    html = fix_type_specimen(html, name)
    html = fix_hash_hosts(html)
    html = ensure_contact_footer(html)
    html = add_font_preload(html)
    html = strip_inline_opacity(html)

    # Final pass: ensure aria-label Primary
    if re.search(r"<nav\b", html, re.I) and not re.search(
        r"<nav\b[^>]*aria-label\s*=\s*[\"']Primary[\"']", html, re.I
    ):
        html = re.sub(r"<nav\b", '<nav aria-label="Primary"', html, count=1, flags=re.I)

    # Ensure --muted present after css ops
    if "--muted" not in html and "--mute" in html:
        html = html.replace(":root {", ":root {\n  --muted: var(--mute);", 1)

    path.write_text(html, encoding="utf-8")


def main() -> None:
    files = sorted(VARIANTS.glob("*.html"))
    for p in files:
        fix_file(p)
        print("fixed", p.name)
    print("done", len(files))


if __name__ == "__main__":
    main()
