# dim_productos_like_powerbi_distinct.py
# Lee:  salida_csv/items.csv  (columna: Descripcion)
# Crea: salida_csv/dim_productos.csv  con Producto_PBI (igual a DAX DISTINCT de Descripcion)
#      y además ProductoStd + Familia/Característica/ProcesoExtra/Material/Medida/Color

from pathlib import Path
import re
import unicodedata
import pandas as pd

BASE_DIR = Path("salida_csv")
ITEMS_CSV = BASE_DIR / "items.csv"
OUT_CSV = BASE_DIR / "dim_productos.csv"

# -----------------------------
# Utilidades
# -----------------------------
REPLACE_CHARS = r"[#\-\*\.,]"  # # - * . ,
MULTISPACE = re.compile(r"\s+")

def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def normalize_text(s: str) -> str:
    s = (s or "")
    s = s.strip()
    if not s:
        return ""

    # Normalización estilo "Python" (lo que ya veníamos haciendo)
    s = strip_accents(s.upper())
    s = re.sub(REPLACE_CHARS, " ", s)

    # unir "2 MM" -> "2MM"
    s = re.sub(r"\b(\d+)\s*MM\b", r"\1MM", s)

    # --- Typos / variantes (ajusta aquí cuando encuentres más) ---
    # DRIZA (incluye DRIZ, DIZA, DRYZA, DRIUZA, DRISA, DRIZAS, etc.)
    s = re.sub(r"\b(DRIUZA|DRYZA|DRISA|DIZA|DRIZAS|DRIZ)\b", "DRIZA", s)

    # ALQUITRANADO
    s = re.sub(r"\bALQUITRANAD[OA]S?\b", "ALQUITRANADO", s)

    # TORCIDO
    s = re.sub(r"\b(TORCIDI|TORZIDO|TORCID[OA]S?)\b", "TORCIDO", s)

    # TRENZADO
    s = re.sub(r"\bTRENZAD[OA]S?\b", "TRENZADO", s)

    # POLIESTER
    s = re.sub(r"\b(DEPOLIESTER|POLYESTER|POLYESTERS|POLIESTERS)\b", "POLIESTER", s)

    # POLIPROPILENO (incluye PP y error POLIPROPIENO)
    s = re.sub(r"\bPOLIPROPIENO\b", "POLIPROPILENO", s)
    s = re.sub(r"\bPP\b", "POLIPROPILENO", s)

    # NYLON (NAYLON)
    s = re.sub(r"\bNAYLON\b", "NYLON", s)

    # SEMIESTATICA
    s = re.sub(r"\bSEMI\s*ESTATICA\b", "SEMIESTATICA", s)

    # Limpieza de ruido
    s = re.sub(r"\bKILOGRAMO(S)?\b", " ", s)
    s = re.sub(r"\bROLLOS?\b", " ", s)
    s = re.sub(r"\bPAGO\s+ANTICIPADO\b", " ", s)

    # Compactar espacios
    s = MULTISPACE.sub(" ", s).strip()
    return s

def tokenize(s: str):
    return s.split(" ") if s else []

# -----------------------------
# Reglas de Familia / Característica / Proceso / Material
# -----------------------------
COLOR_LIST = [
    "BLANCO","NEGRO","ROJO","VERDE","AZUL","AMARILLO","NARANJA","CELESTE","GRIS","MARRON",
    "BEIGE","CREMA","ROSADO","MORADO","VIOLETA","FUCSIA","TURQUESA","DORADO","PLATEADO",
    "NATURAL","COLOR"
]

def pick_family(tokens):
    st = set(tokens)

    # prioridad: ALQUITRANADO gana a todo
    if "ALQUITRANADO" in st:
        return "ALQUITRANADO"

    # DRIZA gana a SOGA
    if "DRIZA" in st:
        return "DRIZA"

    for fam in ["CABO","CINTA","CORDEL","CUERDA","HILO","FIBRA"]:
        if fam in st:
            return fam

    # POLIESTER solo si no cayó en anteriores
    if "POLIESTER" in st:
        return "POLIESTER"

    if "SOGA" in st:
        return "SOGA"

    if "TRENZADO" in st:
        return "TRENZADO"

    return "NO ESPECIFICADO"

def pick_caracteristica(tokens, family):
    st = set(tokens)

    if "SEMIESTATICA" in st:
        return "SEMIESTATICA"
    if "IRLANDES" in st:
        return "IRLANDES"
    if "PLANO" in st:
        return "PLANO"

    if "TORCIDO" in st:
        # Torcido solo si familia HILO (y también útil en CABO)
        if family in ("HILO", "CABO"):
            return "TORCIDO"
        return "TORCIDO"

    # TRENZADO solo si familia CORDEL
    if family == "CORDEL" and "TRENZADO" in st:
        return "TRENZADO"

    return "NO ESPECIFICADO"

def pick_proceso_extra(tokens, family):
    st = set(tokens)
    if "ALQUITRANADO" in st and family != "ALQUITRANADO":
        return "ALQUITRANADO"
    return "NO ESPECIFICADO"

def pick_material(tokens, family, proceso_extra, producto_std):
    st = set(tokens)

    if "MIXTO" in st:
        return "MIXTO"

    # NYLON reglas fuertes
    if family == "CORDEL":
        return "NYLON"
    if proceso_extra == "ALQUITRANADO":
        return "NYLON"
    if "/210" in producto_std:
        return "NYLON"

    # CUERDA: si tiene DIAMETRO o MM => POLIESTER
    if family == "CUERDA" and ("DIAMETRO" in st or any(tok.endswith("MM") for tok in tokens)):
        return "POLIESTER"
    if "/250" in producto_std:
        return "POLIESTER"

    if "MACRAME" in st:
        return "MACRAME"
    if "RAFIA" in st:
        return "RAFIA"
    if "POLIPROPILENO" in st:
        return "POLIPROPILENO"
    if "NYLON" in st:
        return "NYLON"
    if "POLIESTER" in st:
        return "POLIESTER"

    return "NO ESPECIFICADO"

# -----------------------------
# Medida y Color
# -----------------------------
RE_FRAC = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")                 # 48/210, 3/32
RE_DENIER_COMP = re.compile(r"\b(\d{3,5}D/\d{2,4})\b")          # 1000D/192
RE_DENIER = re.compile(r"\b(\d+)\s*(DENIER(S)?)\b")            # 1000 DENIER(S)
RE_D = re.compile(r"\b(\d{3,5})D\b")                           # 1000D
RE_MM = re.compile(r"\b(\d+)\s*MM\b")                          # 2MM
RE_PULG = re.compile(r"\b(\d+)\s*(PULGADAS?|PULG|PUL)\b")       # 3 PULG
RE_PULG_JUNTO = re.compile(r"\b(\d+)(PULGADAS?|PULG|PUL)\b")    # 3PULG
RE_NUM = re.compile(r"\b(\d+)\b")                              # número suelto

def pick_medida(producto_std: str):
    # 1) fracción ##/##
    m = RE_FRAC.search(producto_std)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # 2) denier compuesto 1000D/192
    m = RE_DENIER_COMP.search(producto_std)
    if m:
        return m.group(1)

    # 3) denier: “1000 DENIER(S)” o “1000D”
    m = RE_DENIER.search(producto_std)
    if m:
        return f"{m.group(1)} DENIER"
    m = RE_D.search(producto_std)
    if m:
        return f"{m.group(1)} DENIER"

    # 4) mm
    m = RE_MM.search(producto_std)
    if m:
        return f"{m.group(1)}MM"

    # 5) pulgada (3PULG / 3 PULG)
    m = RE_PULG_JUNTO.search(producto_std)
    if m:
        return f"{m.group(1)} PULGADA"
    m = RE_PULG.search(producto_std)
    if m:
        return f"{m.group(1)} PULGADA"

    # 6) número suelto (último recurso)
    m = RE_NUM.search(producto_std)
    if m:
        return m.group(1)

    return ""

def pick_color(tokens):
    st = set(tokens)
    for c in COLOR_LIST:
        if c in st:
            return c
    return ""

# -----------------------------
# Main
# -----------------------------
def main():
    if not ITEMS_CSV.exists():
        raise FileNotFoundError(f"No existe: {ITEMS_CSV}")

    df_items = pd.read_csv(ITEMS_CSV, encoding="utf-8", low_memory=False)

    # Detecta columna "Descripcion"
    col_desc = None
    for c in df_items.columns:
        if c.strip().lower() == "descripcion":
            col_desc = c
            break
    if col_desc is None:
        raise ValueError(f"No encontré columna 'Descripcion'. Columnas: {list(df_items.columns)}")

    # 1) "DISTINCT" como Power BI: tal cual viene la descripción (sin limpiar)
    df_prod = pd.DataFrame({
        "Producto_PBI": df_items[col_desc].fillna("").astype(str)
    })

    # OJO: Esto imita el DISTINCT crudo: drop_duplicates sobre el texto tal cual
    df_prod = df_prod[df_prod["Producto_PBI"] != ""].drop_duplicates(subset=["Producto_PBI"]).reset_index(drop=True)

    # 2) Ahora sí, hacemos la estandarización "Python"
    df_prod["ProductoStd"] = df_prod["Producto_PBI"].apply(normalize_text)
    df_prod["Tokens"] = df_prod["ProductoStd"].apply(tokenize)
    df_prod["TokensStr"] = df_prod["Tokens"].apply(lambda xs: "|".join(xs))

    # 4) Familia
    df_prod["FamiliaProducto"] = df_prod["Tokens"].apply(pick_family)

    # 5) Característica
    df_prod["Caracteristica"] = df_prod.apply(lambda r: pick_caracteristica(r["Tokens"], r["FamiliaProducto"]), axis=1)

    # 6) Proceso extra
    df_prod["ProcesoExtra"] = df_prod.apply(lambda r: pick_proceso_extra(r["Tokens"], r["FamiliaProducto"]), axis=1)

    # 7) Material
    df_prod["Material"] = df_prod.apply(
        lambda r: pick_material(r["Tokens"], r["FamiliaProducto"], r["ProcesoExtra"], r["ProductoStd"]),
        axis=1
    )

    # 8) Medida
    df_prod["MedidaStd"] = df_prod["ProductoStd"].apply(pick_medida)

    # 9) Color
    df_prod["ColorStd"] = df_prod["Tokens"].apply(pick_color)

    # Guardar
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    df_prod.to_csv(OUT_CSV, index=False, encoding="utf-8")

    print("✅ Listo")
    print(f"Productos DISTINCT estilo Power BI (Producto_PBI): {len(df_prod)}")
    print(f"Archivo generado: {OUT_CSV}")
    print("Relación 1 a 1 sugerida en Power BI: Productos[Producto_PBI] -> Items[Descripcion]")

if __name__ == "__main__":
    main()
