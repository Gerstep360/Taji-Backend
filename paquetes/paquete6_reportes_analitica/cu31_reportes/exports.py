import csv
from html import escape
from io import BytesIO, StringIO

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def export_xlsx(title, columns, rows, tenant, description):
    """Genera un archivo Excel .xlsx sanitizado y estilizado."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Reporte"
    sheet.append([column.label for column in columns])

    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2563EB")

    for row_number, row in enumerate(rows, 2):
        sheet.append(
            [ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value for value in row]
        )
        for index in range(1, len(columns) + 1):
            cell = sheet.cell(row=row_number, column=index)
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, column in enumerate(columns, 1):
        sheet.column_dimensions[get_column_letter(index)].width = min(45, max(18, len(column.label) + 4))

    info = workbook.create_sheet("Configuración")
    for row in [
        ("Reporte", title),
        ("Condominio", tenant.name),
        ("Generado", timezone.localtime().strftime("%d/%m/%Y %H:%M")),
        ("Criterios", description),
    ]:
        info.append(row)

    for row in info:
        for cell in row:
            if isinstance(cell.value, str):
                cell.value = ILLEGAL_CHARACTERS_RE.sub("", cell.value)
                cell.data_type = "s"

    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 80
    output = BytesIO()
    workbook.save(output)
    return HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def export_html(title, columns, rows, tenant, description):
    """Genera una página HTML imprimible y encapsulada con CSP seguro."""
    headings = "".join(f"<th scope='col'>{escape(column.label)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>" for row in rows
    )
    html = f"""<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>
body{{font-family:Arial,sans-serif;color:#162b4d;margin:32px}}h1{{color:#2563eb}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #dbe3ee;padding:10px;text-align:left;white-space:pre-wrap}}
th{{background:#eff6ff}}tr:nth-child(even){{background:#f8fafc}}p{{white-space:pre-wrap}}
.meta{{color:#64748b;font-size:0.9em;margin-bottom:20px}}
</style><h1>{escape(title)}</h1>
<p class="meta">Condominio: <strong>{escape(tenant.name)}</strong> · Generado: {timezone.localtime().strftime("%d/%m/%Y %H:%M")}</p>
<p>{escape(description)}</p>
<table><thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table></html>"""
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return response


def export_pdf(title, columns, rows, tenant, description):
    """PDF paginado, sin navegador, sin ejecutar HTML procedente de los datos."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    output = BytesIO()
    page = landscape(A3) if len(columns) > 8 else landscape(A4) if len(columns) > 4 else A4
    doc = SimpleDocTemplate(output, pagesize=page, rightMargin=30, leftMargin=30,
        topMargin=32, bottomMargin=38, title=title, author="Taji")
    styles = getSampleStyleSheet()
    styles['Title'].textColor = colors.HexColor('#10233C')
    cell = ParagraphStyle('TajiCell', fontName='Helvetica', fontSize=8, leading=11, wordWrap='CJK')
    heading = ParagraphStyle('TajiHeading', parent=cell, textColor=colors.white, fontName='Helvetica-Bold')
    def paragraph(value, style=cell):
        return Paragraph(escape(str(value if value is not None else '')).replace('\n', '<br/>'), style)
    story = [Paragraph('TAJI / REPORTES', styles['Heading3']), paragraph(title, styles['Title']),
        paragraph(tenant.name, styles['Heading2']), paragraph(description), Spacer(1, 16)]
    if not rows:
        story.append(paragraph('No hay registros para los filtros seleccionados.'))
    else:
        data = [[paragraph(column.label, heading) for column in columns]]
        data.extend([[paragraph(value) for value in row] for row in rows])
        table = LongTable(data, colWidths=[doc.width / len(columns)] * len(columns), repeatRows=1, splitInRow=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F6FFF')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F4F7FB')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#DCE4ED')),
        ]))
        story.append(table)
    def footer(canvas, document):
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#6F7F93'))
        canvas.drawString(30, 20, 'Taji | '+timezone.localtime().strftime('%d/%m/%Y %H:%M'))
        canvas.drawRightString(page[0]-30, 20, 'Página '+str(document.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return HttpResponse(output.getvalue(), content_type='application/pdf')


def export_csv(title, columns, rows, tenant, description):
    """Genera un archivo delimitado por comas (CSV) con codificación UTF-8 BOM."""
    output = StringIO()
    # UTF-8 BOM para que Excel en Windows reconozca acentos directamente
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([column.label for column in columns])
    for row in rows:
        writer.writerow(row)
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    return response

