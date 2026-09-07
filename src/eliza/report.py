"""PDF report generation for Eliza DQ checks."""

import math
from datetime import datetime


def generate_pdf(result, path=None, title=None, name=None):
    """Generate a visual PDF report from ElizaResult.

    Args:
        result: ElizaResult from check()
        path: Output path. Auto-generated if None: eliza_{name}_{date}.pdf
        title: Report title. Auto-generated from name if None.
        name: Model/config name (e.g. "orders", "taxi"). Used for filename and title.

    Requires: pip install eliza-dq[report]  (fpdf2)
    """
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError("PDF reports require fpdf2: pip install eliza-dq[report]")

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    if path is None:
        slug = name or "report"
        path = f"eliza_{slug}_{ts}.pdf"
    if title is None:
        title = f"{name} - Data Quality Report" if name else "Data Quality Report"

    passed = sum(1 for c in result.checks if c.status == "pass")
    warned = sum(1 for c in result.checks if c.status == "warn")
    failed = sum(1 for c in result.checks if c.status == "fail")
    errors = sum(1 for c in result.checks if c.status == "error")
    total_checks = len(result.checks)
    health_pct = (passed / total_checks * 100) if total_checks else 100

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    _draw_header(pdf, result, title, health_pct, passed, warned, failed, errors, total_checks)
    _draw_donut(pdf, result, passed, warned, failed, errors, total_checks, health_pct)
    _draw_checks_table(pdf, result)
    _draw_fail_bars(pdf, result)

    if result.samples:
        _draw_samples(pdf, result)

    _draw_footer(pdf, result)

    pdf.output(path)
    return path


# -- Colors ----------------------------------------------------------------

C_PASS = (46, 160, 67)
C_WARN = (219, 171, 9)
C_FAIL = (207, 34, 46)
C_ERR = (130, 130, 130)
C_BG = (246, 248, 250)
C_BORDER = (208, 215, 222)
C_TEXT = (36, 41, 47)
C_MUTED = (101, 109, 118)
C_ACCENT = (9, 105, 218)
C_WHITE = (255, 255, 255)


def _status_color(status):
    return {"pass": C_PASS, "warn": C_WARN, "fail": C_FAIL}.get(status, C_ERR)


# -- Header ----------------------------------------------------------------


def _draw_header(pdf, result, title, health_pct, passed, warned, failed, errors, total_checks):
    pdf.set_fill_color(*C_ACCENT)
    pdf.rect(0, 0, 210, 4, "F")

    pdf.set_y(12)

    report_title = title or "Data Quality Report"
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*C_TEXT)
    pdf.cell(0, 10, report_title, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*C_MUTED)
    ts = datetime.now().strftime("%B %d, %Y at %H:%M")
    pdf.cell(0, 5, f"{ts}  |  {result.total_rows:,} rows  |  {result.elapsed_ms:.0f}ms", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if failed == 0 and errors == 0:
        badge_col = C_PASS
        badge_text = f"HEALTHY  {passed}/{total_checks} passed"
    elif warned > 0 and failed == 0:
        badge_col = C_WARN
        badge_text = f"WARNING  {warned} warnings, {passed} passed"
    else:
        badge_col = C_FAIL
        badge_text = f"ISSUES FOUND  {failed} failed, {passed} passed"

    pdf.set_fill_color(*badge_col)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*C_WHITE)
    bw = pdf.get_string_width(badge_text) + 16
    pdf.cell(bw, 7, f"  {badge_text}  ", new_x="LMARGIN", new_y="NEXT", fill=True)

    pdf.ln(6)
    pdf.set_draw_color(*C_BORDER)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)


# -- Donut chart -----------------------------------------------------------


def _draw_donut(pdf, result, passed, warned, failed, errors, total_checks, health_pct):
    if total_checks == 0:
        return

    cx = 55
    cy = pdf.get_y() + 28
    r_outer = 22
    r_inner = 14

    slices = []
    if passed > 0:
        slices.append((passed / total_checks, C_PASS))
    if warned > 0:
        slices.append((warned / total_checks, C_WARN))
    if failed > 0:
        slices.append((failed / total_checks, C_FAIL))
    if errors > 0:
        slices.append((errors / total_checks, C_ERR))

    angle_start = -90
    for frac, color in slices:
        sweep = frac * 360
        _draw_arc_slice(pdf, cx, cy, r_outer, angle_start, angle_start + sweep, color)
        angle_start += sweep

    _draw_circle_fill(pdf, cx, cy, r_inner, C_WHITE)

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*C_TEXT)
    pct_text = f"{health_pct:.0f}%"
    tw = pdf.get_string_width(pct_text)
    pdf.text(cx - tw / 2, cy + 3, pct_text)

    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*C_MUTED)
    ht = "healthy"
    tw2 = pdf.get_string_width(ht)
    pdf.text(cx - tw2 / 2, cy + 8, ht)

    lx = 90
    ly = cy - 18
    legend = [
        (C_PASS, f"Passed ({passed})"),
        (C_WARN, f"Warnings ({warned})"),
        (C_FAIL, f"Failed ({failed})"),
    ]
    if errors:
        legend.append((C_ERR, f"Errors ({errors})"))

    pdf.set_font("Helvetica", "", 9)
    for color, label in legend:
        pdf.set_fill_color(*color)
        pdf.rect(lx, ly, 4, 4, "F")
        pdf.set_text_color(*C_TEXT)
        pdf.text(lx + 6, ly + 3.5, label)
        ly += 8

    kx = 145
    ky = cy - 18
    _draw_kpi_card(pdf, kx, ky, f"{total_checks}", "Total Checks", C_ACCENT)
    _draw_kpi_card(pdf, kx, ky + 16, f"{result.elapsed_ms:.0f}ms", "Duration", C_MUTED)
    _draw_kpi_card(pdf, kx, ky + 32, f"{result.total_rows:,}", "Rows Scanned", C_MUTED)

    pdf.set_y(cy + 34)
    pdf.set_draw_color(*C_BORDER)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)


def _draw_kpi_card(pdf, x, y, value, label, color):
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*color)
    pdf.text(x, y + 5, value)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*C_MUTED)
    pdf.text(x, y + 10, label)


def _draw_arc_slice(pdf, cx, cy, r, a_start, a_end, color):
    pdf.set_fill_color(*color)
    steps = max(int(abs(a_end - a_start) / 2), 4)
    for i in range(steps):
        t0 = math.radians(a_start + (a_end - a_start) * i / steps)
        t1 = math.radians(a_start + (a_end - a_start) * (i + 1) / steps)
        x0 = cx + r * math.cos(t0)
        y0 = cy + r * math.sin(t0)
        x1 = cx + r * math.cos(t1)
        y1 = cy + r * math.sin(t1)
        _draw_polygon(pdf, [(cx, cy), (x0, y0), (x1, y1)], color)


def _draw_polygon(pdf, points, color):
    pdf.set_fill_color(*color)
    pdf.set_draw_color(*color)
    with pdf.new_path(points[0][0], points[0][1]) as path:
        for p in points[1:]:
            path.line_to(p[0], p[1])
        path.close()


def _draw_circle_fill(pdf, cx, cy, r, color):
    points = []
    for i in range(72):
        angle = math.radians(i * 5)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    pdf.set_fill_color(*color)
    pdf.set_draw_color(*color)
    with pdf.new_path(points[0][0], points[0][1]) as path:
        for p in points[1:]:
            path.line_to(p[0], p[1])
        path.close()


# -- Checks table ----------------------------------------------------------


def _draw_checks_table(pdf, result):
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*C_TEXT)
    pdf.cell(0, 8, "Check Results", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    w_status = 18
    w_col = 45
    w_check = 35
    w_failures = 30
    w_rate = 22
    w_bar = 40
    row_h = 7

    pdf.set_fill_color(*C_BG)
    pdf.set_draw_color(*C_BORDER)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*C_MUTED)

    pdf.cell(w_status, row_h, "STATUS", border="B", fill=True, align="C")
    pdf.cell(w_col, row_h, "COLUMN", border="B", fill=True)
    pdf.cell(w_check, row_h, "CHECK", border="B", fill=True)
    pdf.cell(w_failures, row_h, "FAILURES", border="B", fill=True, align="R")
    pdf.cell(w_rate, row_h, "RATE", border="B", fill=True, align="R")
    pdf.cell(w_bar, row_h, "IMPACT", border="B", fill=True, align="C", new_x="LMARGIN", new_y="NEXT")

    max_fail = max((c.fail_count for c in result.checks), default=1) or 1

    for i, c in enumerate(result.checks):
        bg = C_WHITE if i % 2 == 0 else C_BG
        pdf.set_fill_color(*bg)

        sc = _status_color(c.status)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*sc)
        pdf.cell(w_status, row_h, c.status.upper(), fill=True, align="C")

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*C_TEXT)
        pdf.cell(w_col, row_h, str(c.column or "-")[:22], fill=True)
        pdf.cell(w_check, row_h, c.name[:18], fill=True)

        pdf.set_font("Helvetica", "", 8)
        pdf.cell(w_failures, row_h, f"{c.fail_count:,}", fill=True, align="R")

        pdf.set_text_color(*sc if c.status != "pass" else C_MUTED)
        pdf.cell(w_rate, row_h, f"{c.fail_rate:.2%}", fill=True, align="R")

        bar_x = pdf.get_x() + 2
        bar_y = pdf.get_y() + 2
        bar_max_w = w_bar - 6
        bar_h_px = 3

        pdf.set_fill_color(*bg)
        pdf.cell(w_bar, row_h, "", fill=True, new_x="LMARGIN", new_y="NEXT")

        if c.fail_count > 0:
            bar_fill = max((c.fail_count / max_fail) * bar_max_w, 1.5)
            pdf.set_fill_color(230, 230, 230)
            pdf.rect(bar_x, bar_y, bar_max_w, bar_h_px, "F")
            pdf.set_fill_color(*sc)
            pdf.rect(bar_x, bar_y, bar_fill, bar_h_px, "F")

    pdf.ln(4)


# -- Fail rate horizontal bars --------------------------------------------


def _draw_fail_bars(pdf, result):
    failed_checks = [c for c in result.checks if c.status in ("fail", "warn") and c.fail_count > 0]
    if not failed_checks:
        return

    if pdf.get_y() > 230:
        pdf.add_page()

    pdf.set_draw_color(*C_BORDER)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*C_TEXT)
    pdf.cell(0, 8, "Failure Distribution", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    max_rate = max(c.fail_rate for c in failed_checks) or 0.01
    bar_max_w = 100

    for c in sorted(failed_checks, key=lambda x: -x.fail_rate):
        if pdf.get_y() > 265:
            pdf.add_page()

        label = f"{c.column}:{c.name}" if c.column else c.name
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*C_TEXT)
        pdf.cell(60, 6, label[:30], align="R")

        bar_x = pdf.get_x() + 3
        bar_y = pdf.get_y() + 1.5
        bar_w = max((c.fail_rate / max_rate) * bar_max_w, 2)
        bar_h_px = 3

        sc = _status_color(c.status)
        pdf.set_fill_color(230, 230, 230)
        pdf.rect(bar_x, bar_y, bar_max_w, bar_h_px, "F")
        pdf.set_fill_color(*sc)
        pdf.rect(bar_x, bar_y, bar_w, bar_h_px, "F")

        pdf.set_text_color(*C_MUTED)
        pdf.set_font("Helvetica", "", 7)
        pdf.text(bar_x + bar_max_w + 2, bar_y + 2.5, f"{c.fail_rate:.2%} ({c.fail_count:,})")

        pdf.ln(6)

    pdf.ln(2)


# -- Samples ---------------------------------------------------------------


def _draw_samples(pdf, result):
    failed_samples = {
        k: v
        for k, v in result.samples.items()
        if k in [f"{c.column}:{c.name}" for c in result.checks if c.fail_count > 0]
    }
    if not failed_samples:
        return

    if pdf.get_y() > 220:
        pdf.add_page()

    pdf.set_draw_color(*C_BORDER)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*C_TEXT)
    pdf.cell(0, 8, "Failed Row Samples", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    count = 0
    for name, sdf in failed_samples.items():
        if count >= 4:
            break
        if pdf.get_y() > 250:
            pdf.add_page()

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*C_FAIL)
        pdf.cell(0, 6, name, new_x="LMARGIN", new_y="NEXT")

        rows = sdf.head(3).iter_rows(named=True) if hasattr(sdf, "head") else sdf[:3]
        rows_list = list(rows)

        if not rows_list:
            continue

        cols = list(rows_list[0].keys())[:6]
        col_w = min(30, 180 / len(cols))

        pdf.set_fill_color(*C_BG)
        pdf.set_font("Helvetica", "B", 6)
        pdf.set_text_color(*C_MUTED)
        for col_name in cols:
            pdf.cell(col_w, 5, str(col_name)[:14], border=1, fill=True)
        pdf.ln()

        pdf.set_font("Courier", "", 6)
        pdf.set_text_color(*C_TEXT)
        for row in rows_list:
            for col_name in cols:
                val = str(row.get(col_name, ""))[:14]
                pdf.cell(col_w, 4, val, border=1)
            pdf.ln()

        pdf.ln(3)
        count += 1


# -- Footer ----------------------------------------------------------------


def _draw_footer(pdf, result):
    pdf.ln(4)
    pdf.set_draw_color(*C_BORDER)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(
        0,
        4,
        f"Eliza DQ v0.1  |  {result.total_rows:,} rows  |  {result.elapsed_ms:.0f}ms  |  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        align="C",
    )
