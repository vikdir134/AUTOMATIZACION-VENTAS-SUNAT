import os
import re
import zipfile
import shutil
import csv
import xml.etree.ElementTree as ET

ZIP_DIR = "descargas_zip"
TMP_DIR = "_tmp_extract"
OUT_DIR = "salida_csv"

FACTURAS_CSV = os.path.join(OUT_DIR, "facturas.csv")
ITEMS_CSV = os.path.join(OUT_DIR, "items.csv")
ERRORES_CSV = os.path.join(OUT_DIR, "errores.csv")

# NUEVO: control
RESUMEN_CONTROL_CSV = os.path.join(OUT_DIR, "resumen_control.csv")
FALTANTES_CSV = os.path.join(OUT_DIR, "faltantes.csv")
DUPLICADOS_CSV = os.path.join(OUT_DIR, "duplicados.csv")

# NUEVO: anulaciones (NCE motivo 01)
ANULACIONES_CSV = os.path.join(OUT_DIR, "anulaciones.csv")

# Pon aquí tu total esperado
TOTAL_ESPERADO = 1128

# Namespaces UBL (como tu XML)
NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

def t(elem):
    return (elem.text or "").strip() if elem is not None else ""

def find1(root, path):
    return root.find(path, NS)

def findall(root, path):
    return root.findall(path, NS)

def extract_zip(zip_path, extract_to):
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)

def find_xmls(folder):
    xmls = []
    for rootdir, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".xml"):
                xmls.append(os.path.join(rootdir, f))
    return xmls

def write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

# =========================
# CONTROL: Parseo nombre ZIP
# =========================
ZIP_RE = re.compile(r"^FACTURA([A-Z]\d{3})-(\d+)(\d{11})\.zip$", re.IGNORECASE)

def parse_zip_filename(zip_name):
    m = ZIP_RE.match(zip_name)
    if not m:
        return None
    serie = m.group(1).upper()
    num_str = m.group(2)
    ruc = m.group(3)
    numero = int(num_str)
    return {"serie": serie, "numero": numero, "ruc": ruc}

def control_faltantes(zips, total_esperado):
    parsed = []
    no_parseables = []

    for z in zips:
        info = parse_zip_filename(z)
        if info:
            info["zip"] = z
            parsed.append(info)
        else:
            no_parseables.append(z)

    resumen_rows = []
    faltantes_rows = []
    duplicados_rows = []

    if not parsed:
        resumen_rows.append({
            "Serie": "",
            "RUC": "",
            "TotalZIP": len(zips),
            "ZIP_Validos_Patron": 0,
            "ZIP_NoParseables": len(no_parseables),
            "MinNumero": "",
            "MaxNumero": "",
            "Unicos": 0,
            "Duplicados": 0,
            "Faltantes_EnRango": 0,
            "TotalEsperado": total_esperado,
            "Diferencia_Esperado_vs_Unicos": total_esperado - 0
        })
        for z in no_parseables:
            duplicados_rows.append({"Serie": "", "RUC": "", "Numero": "", "ZIP": z, "Tipo": "NO_PARSEABLE"})
        return resumen_rows, faltantes_rows, duplicados_rows

    series = sorted(set(p["serie"] for p in parsed))

    for serie in series:
        pserie = [p for p in parsed if p["serie"] == serie]
        ruc_set = sorted(set(p["ruc"] for p in pserie))
        ruc_str = ruc_set[0] if len(ruc_set) == 1 else ",".join(ruc_set)

        nums = [p["numero"] for p in pserie]
        min_n, max_n = min(nums), max(nums)

        seen = {}
        for p in pserie:
            key = (p["serie"], p["ruc"], p["numero"])
            seen.setdefault(key, []).append(p["zip"])

        dup_count = 0
        unique_nums = set()
        for (s, r, n), zlist in seen.items():
            unique_nums.add(n)
            if len(zlist) > 1:
                dup_count += (len(zlist) - 1)
                for zname in zlist:
                    duplicados_rows.append({
                        "Serie": s, "RUC": r, "Numero": n, "ZIP": zname, "Tipo": "DUPLICADO"
                    })

        faltantes = []
        for n in range(min_n, max_n + 1):
            if n not in unique_nums:
                faltantes.append(n)
                faltantes_rows.append({"Serie": serie, "RUC": ruc_str, "NumeroFaltante": n})

        resumen_rows.append({
            "Serie": serie,
            "RUC": ruc_str,
            "TotalZIP": len(zips),
            "ZIP_Validos_Patron": len(pserie),
            "ZIP_NoParseables": len(no_parseables),
            "MinNumero": min_n,
            "MaxNumero": max_n,
            "Unicos": len(unique_nums),
            "Duplicados": dup_count,
            "Faltantes_EnRango": len(faltantes),
            "TotalEsperado": total_esperado,
            "Diferencia_Esperado_vs_Unicos": total_esperado - len(unique_nums),
        })

    for z in no_parseables:
        duplicados_rows.append({"Serie": "", "RUC": "", "Numero": "", "ZIP": z, "Tipo": "NO_PARSEABLE"})

    return resumen_rows, faltantes_rows, duplicados_rows

# =========================
# NUEVO: Detectar tipo de XML
# =========================
def localname(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag

def detect_doc_type(root) -> str:
    # Invoice / CreditNote / DebitNote / ...
    return localname(root.tag)

def parse_discrepancy_creditnote(root):
    """
    Para CreditNote:
      - ReferenceID: documento referenciado (ej: E001-1074)
      - ResponseCode: "01" = Anulación de la operación
      - Description: texto del motivo
    """
    ref_id = ""
    motivo_codigo = ""
    motivo_desc = ""

    dr = root.find(".//cac:DiscrepancyResponse", NS)
    if dr is not None:
        ref_id = t(dr.find("cbc:ReferenceID", NS))
        motivo_codigo = t(dr.find("cbc:ResponseCode", NS))
        motivo_desc = t(dr.find("cbc:Description", NS))

    return ref_id, motivo_codigo, motivo_desc

# =========================
# PARSE GENERAL UBL (Invoice + CreditNote)
# =========================
def parse_ubl_document(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    doc_type = detect_doc_type(root)

    doc_id = t(find1(root, ".//cbc:ID"))
    issue_date = t(find1(root, ".//cbc:IssueDate"))
    issue_time = t(find1(root, ".//cbc:IssueTime"))
    currency = t(find1(root, ".//cbc:DocumentCurrencyCode"))

    supplier_ruc = t(find1(root, ".//cac:AccountingSupplierParty//cac:PartyIdentification//cbc:ID"))
    supplier_name = t(find1(root, ".//cac:AccountingSupplierParty//cac:PartyLegalEntity//cbc:RegistrationName"))
    if not supplier_name:
        supplier_name = t(find1(root, ".//cac:AccountingSupplierParty//cac:PartyName//cbc:Name"))

    customer_ruc = t(find1(root, ".//cac:AccountingCustomerParty//cac:PartyIdentification//cbc:ID"))
    customer_name = t(find1(root, ".//cac:AccountingCustomerParty//cac:PartyLegalEntity//cbc:RegistrationName"))
    if not customer_name:
        customer_name = t(find1(root, ".//cac:AccountingCustomerParty//cac:PartyName//cbc:Name"))

    payment_means = t(find1(root, ".//cac:PaymentTerms//cbc:PaymentMeansID"))

    base_imponible = t(find1(root, ".//cac:TaxTotal//cac:TaxSubtotal//cbc:TaxableAmount"))
    igv_total = t(find1(root, ".//cac:TaxTotal//cbc:TaxAmount"))
    subtotal_sin_igv = t(find1(root, ".//cac:LegalMonetaryTotal//cbc:LineExtensionAmount"))
    total = t(find1(root, ".//cac:LegalMonetaryTotal//cbc:PayableAmount"))

    # Para notas (CreditNote)
    ref_id = ""
    motivo_codigo = ""
    motivo_desc = ""
    es_anulacion_operacion = "NO"

    if doc_type == "CreditNote":
        ref_id, motivo_codigo, motivo_desc = parse_discrepancy_creditnote(root)
        if motivo_codigo == "01":
            es_anulacion_operacion = "SI"

    # Clave única (mantengo tu estilo, pero ahora es "DocumentoKey")
    documento_key = f"{supplier_ruc}-{doc_type}-{doc_id}-{issue_date}"

    header = {
        "DocumentoKey": documento_key,
        "TipoDocumentoXML": doc_type,  # Invoice / CreditNote / etc.
        "ArchivoXML": os.path.basename(xml_path),
        "NumeroDocumento": doc_id,
        "FechaEmision": issue_date,
        "HoraEmision": issue_time,
        "Moneda": currency,
        "RUC_Emisor": supplier_ruc,
        "Nombre_Emisor": supplier_name,
        "RUC_Receptor": customer_ruc,
        "Nombre_Receptor": customer_name,
        "FormaPago": payment_means,
        "BaseImponible": base_imponible,
        "IGV": igv_total,
        "SubtotalSinIGV": subtotal_sin_igv,
        "Total": total,

        # Campos de NCE
        "DocReferencia": ref_id,
        "MotivoCodigo": motivo_codigo,
        "MotivoDescripcion": motivo_desc,
        "EsAnulacionOperacion": es_anulacion_operacion,

        # Se completa al final (solo aplica a Invoice/otros)
        "EsAnulado": "NO",
    }

    # ITEMS: solo para Invoice (y opcionalmente para CreditNote si quieres)
    items = []

    if doc_type == "Invoice":
        lines = findall(root, ".//cac:InvoiceLine")
        for line in lines:
            line_id = t(line.find("cbc:ID", NS))

            qty_el = line.find("cbc:InvoicedQuantity", NS)
            qty = t(qty_el)
            unit = qty_el.attrib.get("unitCode", "") if qty_el is not None else ""

            desc = t(line.find(".//cac:Item//cbc:Description", NS))
            valor_linea = t(line.find("cbc:LineExtensionAmount", NS))
            precio_unit = t(line.find(".//cac:Price//cbc:PriceAmount", NS))
            impuesto_linea = t(line.find(".//cac:TaxTotal//cbc:TaxAmount", NS))

            items.append({
                "DocumentoKey": documento_key,
                "TipoDocumentoXML": doc_type,
                "NumeroDocumento": doc_id,
                "FechaEmision": issue_date,
                "LineaID": line_id,
                "Descripcion": desc,
                "Cantidad": qty,
                "Unidad": unit,
                "PrecioUnitario": precio_unit,
                "ValorLineaSinIGV": valor_linea,
                "ImpuestoLinea": impuesto_linea,
                "RUC_Receptor": customer_ruc,
                "Nombre_Receptor": customer_name,
            })

    return header, items

def main():
    os.makedirs(ZIP_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    # ====== CONTROL ANTES DE PROCESAR ======
    zips = sorted([f for f in os.listdir(ZIP_DIR) if f.lower().endswith(".zip")])
    resumen_rows, faltantes_rows, duplicados_rows = control_faltantes(zips, TOTAL_ESPERADO)

    write_csv(RESUMEN_CONTROL_CSV, resumen_rows, list(resumen_rows[0].keys()) if resumen_rows else ["Serie"])
    write_csv(FALTANTES_CSV, faltantes_rows, ["Serie", "RUC", "NumeroFaltante"])
    write_csv(DUPLICADOS_CSV, duplicados_rows, ["Serie", "RUC", "Numero", "ZIP", "Tipo"])

    # ====== PROCESO XML A CSV ======
    docs_rows = []      # antes facturas_rows
    items_rows = []
    errores_rows = []

    # NUEVO: aquí guardo anulaciones detectadas
    anulaciones_rows = []

    for zname in zips:
        zip_path = os.path.join(ZIP_DIR, zname)

        if os.path.exists(TMP_DIR):
            shutil.rmtree(TMP_DIR)
        os.makedirs(TMP_DIR, exist_ok=True)

        try:
            extract_zip(zip_path, TMP_DIR)
        except Exception as e:
            errores_rows.append({"ZIP_Origen": zname, "ArchivoXML": "", "Error": f"No se pudo extraer ZIP: {e}"})
            continue

        xml_files = find_xmls(TMP_DIR)
        if not xml_files:
            errores_rows.append({"ZIP_Origen": zname, "ArchivoXML": "", "Error": "ZIP sin XML"})
            continue

        for xml_path in xml_files:
            try:
                header, items = parse_ubl_document(xml_path)
                header["ZIP_Origen"] = zname
                docs_rows.append(header)
                items_rows.extend(items)

                # Si es CreditNote y es anulación (motivo 01), guardo detalle
                if header.get("TipoDocumentoXML") == "CreditNote" and header.get("EsAnulacionOperacion") == "SI":
                    anulaciones_rows.append({
                        "ZIP_Origen": zname,
                        "ArchivoXML": header.get("ArchivoXML", ""),
                        "NumeroNCE": header.get("NumeroDocumento", ""),
                        "FechaNCE": header.get("FechaEmision", ""),
                        "DocReferencia": header.get("DocReferencia", ""),  # documento anulado
                        "MotivoCodigo": header.get("MotivoCodigo", ""),
                        "MotivoDescripcion": header.get("MotivoDescripcion", ""),
                        "RUC_Emisor": header.get("RUC_Emisor", ""),
                        "RUC_Receptor": header.get("RUC_Receptor", ""),
                        "TotalNCE": header.get("Total", ""),
                        "Moneda": header.get("Moneda", ""),
                    })

            except Exception as e:
                errores_rows.append({"ZIP_Origen": zname, "ArchivoXML": os.path.basename(xml_path), "Error": str(e)})

    # ====== MARCAR FACTURAS ANULADAS ======
    # Construyo set de documentos anulados por NCE motivo 01 (DocReferencia)
    docs_anulados = set()
    for a in anulaciones_rows:
        ref = (a.get("DocReferencia") or "").strip()
        if ref:
            docs_anulados.add(ref)

    # Marco EsAnulado = SI en documentos que coincidan con DocReferencia
    for d in docs_rows:
        # Solo tiene sentido marcar anulados a documentos "Invoice"
        if d.get("TipoDocumentoXML") == "Invoice":
            num = (d.get("NumeroDocumento") or "").strip()
            if num and num in docs_anulados:
                d["EsAnulado"] = "SI"
            else:
                d["EsAnulado"] = "NO"

    # ====== CAMPOS DE SALIDA ======
    facturas_fields = [
        "DocumentoKey", "ZIP_Origen", "ArchivoXML",
        "TipoDocumentoXML", "NumeroDocumento",
        "FechaEmision", "HoraEmision", "Moneda",
        "RUC_Emisor", "Nombre_Emisor",
        "RUC_Receptor", "Nombre_Receptor",
        "FormaPago",
        "BaseImponible", "IGV", "SubtotalSinIGV", "Total",

        # NCE
        "DocReferencia", "MotivoCodigo", "MotivoDescripcion", "EsAnulacionOperacion",

        # Lo que tú quieres para filtrar en Power BI
        "EsAnulado",
    ]

    items_fields = [
        "DocumentoKey", "TipoDocumentoXML", "NumeroDocumento", "FechaEmision",
        "LineaID", "Descripcion", "Cantidad", "Unidad",
        "PrecioUnitario", "ValorLineaSinIGV", "ImpuestoLinea",
        "RUC_Receptor", "Nombre_Receptor",
    ]

    errores_fields = ["ZIP_Origen", "ArchivoXML", "Error"]

    anulaciones_fields = [
        "ZIP_Origen", "ArchivoXML",
        "NumeroNCE", "FechaNCE",
        "DocReferencia",
        "MotivoCodigo", "MotivoDescripcion",
        "RUC_Emisor", "RUC_Receptor",
        "TotalNCE", "Moneda"
    ]

    write_csv(FACTURAS_CSV, docs_rows, facturas_fields)
    write_csv(ITEMS_CSV, items_rows, items_fields)
    write_csv(ERRORES_CSV, errores_rows, errores_fields)
    write_csv(ANULACIONES_CSV, anulaciones_rows, anulaciones_fields)

    print("✅ Listo")
    print(f"ZIP encontrados: {len(zips)}")
    print(f"Resumen control -> {RESUMEN_CONTROL_CSV}")
    print(f"Faltantes -> {FALTANTES_CSV}")
    print(f"Duplicados/No-parseables -> {DUPLICADOS_CSV}")
    print(f"Documentos (facturas + notas) -> {FACTURAS_CSV}")
    print(f"Items (solo Invoice) -> {ITEMS_CSV}")
    print(f"Anulaciones (NCE motivo 01) -> {ANULACIONES_CSV}")
    print(f"Errores -> {ERRORES_CSV}")

    # Mensaje rápido del control
    if resumen_rows:
        for r in resumen_rows:
            print(
                f"Serie {r['Serie']} | Unicos={r['Unicos']} | Esperado={r['TotalEsperado']} | "
                f"Dif={r['Diferencia_Esperado_vs_Unicos']} | FaltantesEnRango={r['Faltantes_EnRango']} | "
                f"Duplicados={r['Duplicados']} | NoParseables={r['ZIP_NoParseables']}"
            )

    # Mensaje rápido de anulaciones
    print(f"NCE de anulación detectadas: {len(anulaciones_rows)}")
    print(f"Documentos marcados como anulados (Invoice): {sum(1 for d in docs_rows if d.get('TipoDocumentoXML')=='Invoice' and d.get('EsAnulado')=='SI')}")

if __name__ == "__main__":
    main()
