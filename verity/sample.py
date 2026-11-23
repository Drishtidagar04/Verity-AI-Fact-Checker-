"""A small, clearly synthetic sample document for trying the app (13 mixed claims: true, false, outdated and
unverifiable). It contains only INPUT text; no answers or verdicts are stored anywhere."""
from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SAMPLE_CLAIMS = ['The chemical formula of water is H2O.', 'The United Nations officially came into existence on 24 October 1945.', 'The Eiffel Tower is located in Berlin, Germany.', 'The Great Wall of China is easily visible to the unaided human eye from the Moon.', 'An adult human skeleton typically contains 206 bones.', 'The Burj Khalifa is 1,250 metres tall.', 'The Amazon rainforest covers about 12 million square kilometres.', "The world's population is approximately 7 billion people.", "India's population is about 1.2 billion people.", "The concentration of carbon dioxide in Earth's atmosphere is about 400 parts per million.", 'Pluto is classified as the ninth planet of the solar system.', 'The Pacific Ocean is the largest ocean on Earth.', 'Acme Industries recorded an internal customer churn rate of 4.1% in its 2023 fiscal year.']


def build_sample_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Verity AI sample trap document")
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, 800, "Verity AI - Sample Evaluation Document")
    c.setFont("Helvetica", 11)
    y = 765
    for i, text in enumerate(SAMPLE_CLAIMS, 1):
        c.drawString(50, y, f"{i}. {text}")
        y -= 32
    c.save()
    return buf.getvalue()
