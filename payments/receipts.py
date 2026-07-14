"""Server-side PDF receipt generation (reportlab, no external calls)."""

import io

from django.conf import settings
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def build_receipt_pdf(payment):
    """Render a completed payment into a compact A5 PDF receipt (bytes).

    Amounts are written as ``PHP <n>`` rather than the ₱ glyph because the
    built-in Helvetica font has no peso sign; this keeps the output portable.
    """
    reservation = payment.reservation
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A5)
    width, height = A5
    left = 18 * mm
    y = height - 20 * mm

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(left, y, settings.SITE_NAME)
    y -= 7 * mm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(left, y, "Official payment receipt")
    y -= 4 * mm
    pdf.line(left, y, width - left, y)
    y -= 9 * mm

    amount = f"PHP {payment.amount_cents / 100:,.2f}"
    rows = [
        ("Reference", payment.reference or str(payment.pk)),
        ("Reservation", reservation.code),
        ("Customer", reservation.customer.get_full_name() or reservation.customer.username),
        ("Slot", f"{reservation.slot.code} ({reservation.slot.floor.name})"),
        ("Window", f"{reservation.start_at:%b %d, %Y %H:%M} - {reservation.end_at:%H:%M}"),
        ("Method", (payment.method or "online").upper()),
        ("Paid at", f"{payment.paid_at:%b %d, %Y %H:%M}" if payment.paid_at else "-"),
        ("Status", "PAID"),
        ("Amount", amount),
    ]
    for label, value in rows:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(left, y, f"{label}:")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(left + 32 * mm, y, str(value))
        y -= 8 * mm

    y -= 4 * mm
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(left, y, "Thank you. Please keep this receipt for your records.")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
