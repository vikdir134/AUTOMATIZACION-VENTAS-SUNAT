import os
import zipfile
import shutil
import csv
import xml.etree.ElementTree as ET

ZIP_DIR = "descargas_zip"
TMP_DIR = "_tmp_extract"
OUT_DIR = "salida_csv"

NC_CSV = os.path.join(OUT_DIR, "notas_credito.csv")
NC_ITEMS_CSV = os.path.join(OUT_DIR, "notas_credito_items.csv")
ERRORES_CSV = os.path.join(OUT_DIR, "errores.csv")

# Namespaces UBL
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

def localname(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag

def detect_doc_type(root) -> str:
    return localname(root.tag)

def norm_doc_id(s: str) -> str:
    # Normaliza "E001 - 1093" => "E001-1093"
    s = (s or "").strip().upper()
    s = s.replace(" ", "")
    s = s.replace("–", "-").replace("—", "-")
    # si quedó como E001-1093 ok, si quedó E001-1093 ya ok
    return s

def parse_creditnote_reference(root):
    """
    Retorna:
      ref_id_raw, ref_id_norm, motivo_codigo, motivo_desc
    Busca en:
      1) DiscrepancyResponse/ReferenceID
      2) BillingReference/InvoiceDocumentReference/ID (fallback)
    """
    ref_raw = ""
    motivo_codigo = ""
    motivo_desc = ""

    dr = root.find(".//cac:DiscrepancyResponse", NS)
    if dr is not None:
        ref_raw = t(dr.find("cbc:ReferenceID", NS))
        motivo_codigo = t(dr.find("cbc:ResponseCode", NS))
        motivo_desc = t(dr.find("cbc:Description", NS))

    if not ref_raw:
        br = root.find(".//cac:BillingReference//cac:InvoiceDocumentReference//cbc:ID", NS)
        ref_raw = t(br)

    return ref_raw, norm_doc_id(ref_raw), motivo_codigo, motivo_desc

def parse_creditnote(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    if detect_doc_type(root) != "CreditNote":
        raise ValueError("El XML no es CreditNote")

    nc_id = t(find1(root, ".//cbc:ID"))
    issue_date = t(find1(root, ".//cbc:IssueDate"))
    issue_time = t(find1(root, ".//cbc:IssueTime"))
    currency = t(find1(root, ".//cbc:DocumentCurrencyCode"))

    # Emisor
    supplier_ruc = t(find1(root, ".//cac:AccountingSupplierParty//cac:PartyIdentification//cbc:ID"))
    supplier_name = t(find1(root, ".//cac:AccountingSupplierParty//cac:PartyLegalEntity//cbc:RegistrationName"))
    if not supplier_name:
        supplier_name = t(find1(root, ".//cac:AccountingSupplierParty//cac:PartyName//cbc:Name"))

    # Receptor
    customer_ruc = t(find1(root, ".//cac:AccountingCustomerParty//cac:PartyIdentification//cbc:ID"))
    customer_name = t(find1(root, ".//cac:AccountingCustomerParty//cac:PartyLegalEntity//cbc:RegistrationName"))
    if not customer_name:
        customer_name = t(find1(root, ".//cac:AccountingCustomerParty//cac:PartyName//cbc:Name"))

    # Referencia y motivo
    ref_raw, ref_norm, motivo_codigo, motivo_desc = parse_creditnote_reference(root)
    es_anulacion = "SI" if motivo_codigo == "01" else "NO"

    # Totales
    base_imponible = t(find1(root, ".//cac:TaxTotal//cac:TaxSubtotal//cbc:TaxableAmount"))
    igv_total = t(find1(root, ".//cac:TaxTotal//cbc:TaxAmount"))
    subtotal_sin_igv = t(find1(root, ".//cac:LegalMonetaryTotal//cbc:LineExtensionAmount"))
    total = t(find1(root, ".//cac:LegalMonetaryTotal//cbc:PayableAmount"))

    nc_key = f"{supplier_ruc}-CN-{nc_id}-{issue_date}"

    header = {
        "NotaCreditoKey": nc_key,
        "ArchivoXML": os.path.basename(xml_path),
        "NumeroNotaCredito": nc_id,
        "FechaEmision": issue_date,
        "HoraEmision": issue_time,
        "Moneda": currency,

        "RUC_Emisor": supplier_ruc,
        "Nombre_Emisor": supplier_name,
        "RUC_Receptor": customer_ruc,
        "Nombre_Receptor": customer_name,

        "DocReferencia": ref_raw,
        "DocReferencia_Normalizado": ref_norm,
        "MotivoCodigo": motivo_codigo,
        "MotivoDescripcion": motivo_desc,
        "EsAnulacionOperacion": es_anulacion,

        "BaseImponible": base_imponible,
        "IGV": igv_total,
        "SubtotalSinIGV": subtotal_sin_igv,
        "Total": total,
    }

    # Items (CreditNoteLine)
    items = []
    lines = findall(root, ".//cac:CreditNoteLine")

    for line in lines:
        line_id = t(line.find("cbc:ID", NS))

        qty_el = line.find("cbc:CreditedQuantity", NS)
        qty = t(qty_el)
        unit = qty_el.attrib.get("unitCode", "") if qty_el is not None else ""

        desc = t(line.find(".//cac:Item//cbc:Description", NS))
        valor_linea = t(line.find("cbc:LineExtensionAmount", NS))
        precio_unit = t(line.find(".//cac:Price//cbc:PriceAmount", NS))
        impuesto_linea = t(line.find(".//cac:TaxTotal//cbc:TaxAmount", NS))

        items.append({
            "NotaCreditoKey": nc_key,
            "NumeroNotaCredito": nc_id,
            "FechaEmision": issue_date,
            "LineaID": line_id,
            "Descripcion": desc,
            "Cantidad": qty,
            "Unidad": unit,
            "PrecioUnitario": precio_unit,
            "ValorLineaSinIGV": valor_linea,
            "ImpuestoLinea": impuesto_linea,

            "DocReferencia_Normalizado": ref_norm,
            "MotivoCodigo": motivo_codigo,
            "EsAnulacionOperacion": es_anulacion,
        })

    return header, items

def main():
    os.makedirs(ZIP_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    zips = sorted([f for f in os.listdir(ZIP_DIR) if f.lower().endswith(".zip")])

    nc_rows = []
    nc_items_rows = []
    errores_rows = []

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
                header, items = parse_creditnote(xml_path)
                header["ZIP_Origen"] = zname
                nc_rows.append(header)
                nc_items_rows.extend(items)
            except Exception as e:
                errores_rows.append({"ZIP_Origen": zname, "ArchivoXML": os.path.basename(xml_path), "Error": str(e)})

    nc_fields = [
        "NotaCreditoKey", "ZIP_Origen", "ArchivoXML",
        "NumeroNotaCredito", "FechaEmision", "HoraEmision", "Moneda",
        "RUC_Emisor", "Nombre_Emisor",
        "RUC_Receptor", "Nombre_Receptor",
        "DocReferencia", "DocReferencia_Normalizado",
        "MotivoCodigo", "MotivoDescripcion", "EsAnulacionOperacion",
        "BaseImponible", "IGV", "SubtotalSinIGV", "Total",
    ]

    nc_items_fields = [
        "NotaCreditoKey", "NumeroNotaCredito", "FechaEmision",
        "LineaID", "Descripcion", "Cantidad", "Unidad",
        "PrecioUnitario", "ValorLineaSinIGV", "ImpuestoLinea",
        "DocReferencia_Normalizado", "MotivoCodigo", "EsAnulacionOperacion",
    ]

    errores_fields = ["ZIP_Origen", "ArchivoXML", "Error"]

    write_csv(NC_CSV, nc_rows, nc_fields)
    write_csv(NC_ITEMS_CSV, nc_items_rows, nc_items_fields)
    write_csv(ERRORES_CSV, errores_rows, errores_fields)

    print("✅ Listo")
    print(f"ZIP encontrados: {len(zips)}")
    print(f"Notas de crédito -> {NC_CSV}")
    print(f"Items NCE -> {NC_ITEMS_CSV}")
    print(f"Errores -> {ERRORES_CSV}")
    print(f"NCE detectadas: {len(nc_rows)}")
    print(f"NCE Anulación (Motivo 01): {sum(1 for r in nc_rows if r.get('EsAnulacionOperacion')=='SI')}")

if __name__ == "__main__":
    main()
