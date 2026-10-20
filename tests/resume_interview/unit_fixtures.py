"""Synthetic fixtures shared by the Resume Interview tests. NO real person's data: every name, number and address below is made up."""

import io
import zipfile

RESUME = """Asha Verma
Phone: +91 98765 43210 | asha.verma@example.com | linkedin.com/in/asha-verma | github.com/ashav
Mumbai, Maharashtra

SUMMARY
Data analyst with 2 years of experience in dashboards and reporting for sales teams.

EXPERIENCE
Acme Analytics - Data Analyst (2022 - 2024)
• Built Power BI dashboards for the sales team, reducing weekly reporting time from 2 days to 3 hours.
• Wrote SQL queries on PostgreSQL to clean and join tables with 5 million rows.
• Presented monthly insights to the regional manager.

PROJECTS
Customer churn analysis - used Python and pandas to find the drivers of churn for a telecom dataset.

EDUCATION
B.Sc. Statistics, Pune University (2018 - 2021)

SKILLS
SQL, Power BI, Excel, Python, pandas

PERSONAL DETAILS
Date of Birth: 12/03/1999
Father's Name: Ramesh Verma
Marital Status: Single
Nationality: Indian
Address: 12, Gandhi Road, Andheri
Mumbai 400053

DECLARATION
I hereby declare that the above information is true.
"""

JD = """Data Analyst
Acme Corp is hiring a Data Analyst to join the reporting team.
Requirements
- 2+ years of experience in data analysis
- Strong SQL skills (PostgreSQL or MySQL)
- Experience building dashboards in Power BI or Tableau
- Python or R for data cleaning
- Ability to explain insights to non-technical stakeholders
Nice to have
- Experience with Snowflake or BigQuery
- Knowledge of A/B testing
""" * 2


def verhoeff_check_digit(num: str) -> str:
    from app.resume_interview import docs
    d = docs._D
    p = docs._PERM
    inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = d[c][p[(i + 1) % 8][int(ch)]]
    return str(inv[c])


def make_pdf(lines, encrypt_user=None, blank=False) -> bytes:
    """A minimal valid PDF with one text page (hand-written; optionally encrypted via pypdf)."""
    content = "BT /F1 11 Tf 40 780 Td 14 TL\n" + "".join("(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*\n" for l in lines) + "ET"
    if blank:
        content = ""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    data = bytes(out)
    if encrypt_user is not None:
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
        w.encrypt(encrypt_user, owner_password="owner-pw", algorithm="AES-128")
        b = io.BytesIO()
        w.write(b)
        data = b.getvalue()
    return data


def make_pdf_bomb(n_ops: int = 1_500_000) -> bytes:
    """A small valid PDF (~100 KB) whose compressed content stream holds `n_ops` text operations: cheap to send, expensive to parse - the shape of
    file that used to hold an extraction slot for 10 s."""
    import zlib
    stream = zlib.compress(b"BT /F1 11 Tf 40 780 Td (x) Tj ET\n" * n_ops, 9)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def make_docx(paragraphs, extra_xml="") -> bytes:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs) + extra_xml
    xml = f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{body}</w:body></w:document>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return b.getvalue()




ANSWER_GOOD = ("In my last role at Acme Analytics I built Power BI dashboards for the sales team. For example, the weekly report used to take two days, "
               "and I automated it with SQL and Python so it took three hours. This reduced the time by about 80 percent and the managers could review numbers every morning. "
               "I also presented the results to the regional manager, and basically the team started to trust the data more.")
ANSWER_WEAK = ("ANSWER_WEAK I make dashboard for the team and it was good work and everybody liked it very much because the dashboard was nice and the team was happy "
               "with the work that I did there in my company at that time and I think it was fine for everyone")
