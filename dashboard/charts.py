"""Server-rendered inline-SVG charts — no JS/CDN, theme-aware via CSS vars.

Colours reference the site's CSS custom properties (``var(--maroon)`` etc.), so
the same markup adapts to light/dark mode automatically when inlined in the page.
Numbers come from trusted aggregates only, so the output is marked safe.
"""

from django.utils.html import escape
from django.utils.safestring import mark_safe

_W = 640


def line_chart_svg(series, *, height=170, title="Occupancy over time"):
    """Area+line chart of occupied count over time. ``series`` = occupancy_series()."""
    if not series:
        return ""
    values = [s["occupied"] for s in series]
    scale_max = max([s["total"] for s in series] + [1])
    n = len(values)
    pad = 26

    def px(i):
        return pad + (_W - 2 * pad) * (i / (n - 1) if n > 1 else 0)

    def py(v):
        return height - pad - (height - 2 * pad) * (v / scale_max)

    line = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(values))
    area = (
        f"M {px(0):.1f},{height - pad:.1f} "
        + " ".join(f"L {px(i):.1f},{py(v):.1f}" for i, v in enumerate(values))
        + f" L {px(n - 1):.1f},{height - pad:.1f} Z"
    )
    t = escape(title)
    return mark_safe(
        f'<svg class="chart" viewBox="0 0 {_W} {height}" role="img" aria-label="{t}" '
        f'preserveAspectRatio="none" style="width:100%;height:{height}px">'
        f"<title>{t}</title>"
        f'<line x1="{pad}" y1="{height - pad}" x2="{_W - pad}" y2="{height - pad}" stroke="var(--line)"/>'
        f'<text x="{pad}" y="{pad - 8}" font-size="11" fill="var(--muted)">peak {scale_max}</text>'
        f'<path d="{area}" fill="var(--maroon)" opacity="0.12"/>'
        f'<polyline points="{line}" fill="none" stroke="var(--maroon)" stroke-width="2"/>'
        f"</svg>"
    )


def bar_chart_svg(items, *, height=180, title="Reservation status mix"):
    """Vertical bar chart. ``items`` = list of (label, value, css_color)."""
    if not items:
        return ""
    max_v = max([v for _, v, _ in items] + [1])
    n = len(items)
    pad = 30
    slot = (_W - 2 * pad) / n
    bw = slot * 0.6
    parts = [f"<title>{escape(title)}</title>"]
    for i, (label, value, color) in enumerate(items):
        bx = pad + i * slot + (slot - bw) / 2
        bh = (height - 2 * pad) * (value / max_v)
        by = height - pad - bh
        lbl = escape(str(label))
        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" '
            f'fill="{color}"><title>{lbl}: {value}</title></rect>'
            f'<text x="{bx + bw / 2:.1f}" y="{height - pad + 15:.1f}" text-anchor="middle" '
            f'font-size="11" fill="var(--muted)">{lbl}</text>'
            f'<text x="{bx + bw / 2:.1f}" y="{by - 4:.1f}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink)">{value}</text>'
        )
    return mark_safe(
        f'<svg class="chart" viewBox="0 0 {_W} {height}" role="img" '
        f'aria-label="{escape(title)}" style="width:100%;height:{height}px">'
        + "".join(parts)
        + "</svg>"
    )
