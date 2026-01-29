# AUTOMATIZACIÓN PYTHON – VENTAS POR SUNAT (FACTURAS + NOTAS DE CRÉDITO)

Este repositorio automatiza el procesamiento de comprobantes electrónicos SUNAT en formato **ZIP (XML UBL)** para generar **CSV listos para Power BI**.  
El objetivo es transformar facturas y notas de crédito en tablas estructuradas, detectar anulaciones e inconsistencias y facilitar el modelamiento (relaciones 1 a 1 / 1 a muchos) para análisis.

---

## 1) Estructura del proyecto

```

AUTOMATIZACION PYTHON VENTAS POR SUNAT
│
├─ VENTAS
│  ├─ descargas_zip
│  │  └─ (ZIPS de las FACTURAS)
│  ├─ main.py                      # Procesa facturas (y marca anuladas si detecta NCE motivo 01)
│  ├─ main_dim_productos.py        # Genera dim_productos.csv tipo DISTINCT Power BI + estandarización
│  └─ salida_csv                   # (Se genera automáticamente)
│
└─ NOTAS DE CREDITO
├─ descargas_zip
│  └─ (ZIPS de las NOTAS DE CRÉDITO)
├─ main.py                      # Procesa CreditNote y genera notas_credito.csv + items
└─ salida_csv                   # (Se genera automáticamente)

````

---

## 2) Requisitos

- Python 3.10+ recomendado
- Librerías:
  - Incluidas en Python: `os`, `zipfile`, `shutil`, `csv`, `re`, `unicodedata`, `xml.etree.ElementTree`, `pathlib`
  - Externa: `pandas` (solo para la dimensión de productos)

Instalar dependencias:
```bash
pip install pandas
````

---

## 3) Qué genera el proyecto (salidas)

### A) VENTAS/salida_csv (facturas)

El script `VENTAS/main.py` genera:

* `facturas.csv`
  Cabecera de documentos (Invoice y, si se encuentra, también CreditNote dentro de los ZIP). Incluye columna **EsAnulado** para filtrar en Power BI.
* `items.csv`
  Detalle por línea (InvoiceLine). Ideal para análisis a nivel producto.
* `anulaciones.csv`
  Resumen de notas de crédito detectadas como anulación (motivo `01`), con documento referenciado.
* `errores.csv`
  XML/ZIP que fallaron o no pudieron leerse.
* Control de integridad (si lo tienes habilitado en tu versión):
  `resumen_control.csv`, `faltantes.csv`, `duplicados.csv`

### B) VENTAS/salida_csv (dimensión productos)

El script `VENTAS/main_dim_productos.py` genera:

* `dim_productos.csv`
  Incluye:

  * `Producto_PBI` (idéntico al DISTINCT crudo de Power BI sobre Items[Descripcion])
  * `ProductoStd` (texto normalizado)
  * `FamiliaProducto`, `Caracteristica`, `ProcesoExtra`, `Material`, `MedidaStd`, `ColorStd`
  * `TokensStr` para auditoría

### C) NOTAS DE CREDITO/salida_csv (notas de crédito)

El script `NOTAS DE CREDITO/main.py` genera:

* `notas_credito.csv`
  Cabecera de la CreditNote (motivo, documento referenciado normalizado, moneda, totales).
* `notas_credito_items.csv`
  Detalle por línea (CreditNoteLine).
* `errores.csv`
  XML/ZIP problemáticos.

---

## 4) Cómo usar el proyecto (paso a paso)

### Paso 1: Descargar los ZIP desde SUNAT

* Descarga los comprobantes desde el portal SUNAT en formato ZIP.
* Mantén separados:

  * ZIPs de FACTURAS → carpeta VENTAS
  * ZIPs de NOTAS DE CRÉDITO → carpeta NOTAS DE CREDITO

### Paso 2: Procesar FACTURAS (VENTAS)

1. Copia los ZIP de facturas a:

   ```
   VENTAS/descargas_zip/
   ```
2. Ejecuta:

   ```bash
   cd "VENTAS"
   python main.py
   ```
3. Verifica los CSV generados en:

   ```
   VENTAS/salida_csv/
   ```

### Paso 3: Generar DIM PRODUCTOS (VENTAS)

1. Asegúrate de tener generado `VENTAS/salida_csv/items.csv`
2. Ejecuta:

   ```bash
   cd "VENTAS"
   python main_dim_productos.py
   ```
3. Se generará:

   ```
   VENTAS/salida_csv/dim_productos.csv
   ```

### Paso 4: Procesar NOTAS DE CRÉDITO (por separado)

1. Copia los ZIP de notas de crédito a:

   ```
   NOTAS DE CREDITO/descargas_zip/
   ```
2. Ejecuta:

   ```bash
   cd "NOTAS DE CREDITO"
   python main.py
   ```
3. Verifica los CSV generados en:

   ```
   NOTAS DE CREDITO/salida_csv/
   ```

---

## 5) Importar a Power BI y modelar

### Tablas recomendadas a importar

Desde **VENTAS/salida_csv**:

* `facturas.csv`
* `items.csv`
* `dim_productos.csv`

Desde **NOTAS DE CREDITO/salida_csv**:

* `notas_credito.csv`
* `notas_credito_items.csv`

### Relaciones recomendadas

* `facturas[NumeroDocumento]` 1 → * `items[NumeroDocumento]`
* `dim_productos[Producto_PBI]` 1 → * `items[Descripcion]`
* Para cruzar anulaciones por referencia:

  * `notas_credito[DocReferencia_Normalizado]` → `facturas[NumeroDocumento]`
    (esto funciona bien porque el script normaliza formatos tipo `E001 - 1093` → `E001-1093`)

### Cómo filtrar anuladas

* En `facturas.csv` usa:

  * `EsAnulado = "NO"` para reportes de ventas netas
* En notas de crédito:

  * `EsAnulacionOperacion = "SI"` indica motivo SUNAT `01` (anulación)

---

## 6) Descripción técnica de los scripts

### VENTAS/main.py (facturas)

Funcionalidades principales:

* Extrae todos los XML dentro de ZIP
* Detecta tipo de documento UBL (Invoice/CreditNote)
* Extrae cabecera (RUCs, nombres, moneda, totales, forma de pago)
* Extrae detalle (líneas de factura)
* Detecta notas de crédito motivo `01` y marca la factura referenciada como anulada (`EsAnulado = SI`)

---

### NOTAS DE CREDITO/main.py (notas de crédito)

Funcionalidades principales:

* Procesa únicamente XML tipo `CreditNote`
* Extrae referencia del documento afectado desde:

  * `cac:DiscrepancyResponse/cbc:ReferenceID` (principal)
  * o `cac:BillingReference/.../cbc:ID` (fallback)
* Normaliza el ID referenciado:

  * `"E001 - 1093"` → `"E001-1093"`
* Genera tablas:

  * Cabecera de nota de crédito
  * Líneas (CreditNoteLine) con cantidades, unidad, descripción, montos e IGV
* Marca si es anulación:

  * `MotivoCodigo == "01"` → `EsAnulacionOperacion = "SI"`

---

### VENTAS/main_dim_productos.py (dimensión de productos)

Funcionalidades principales:

* Replica el `DISTINCT(Items[Descripcion])` de Power BI creando `Producto_PBI`
* Luego estandariza texto (`ProductoStd`) y clasifica:

  * Familia
  * Característica
  * Proceso extra
  * Material
  * Medida
  * Color
* Esto permite:

  * relación 1 a 1 / 1 a muchos estable
  * segmentar productos aunque existan variaciones ortográficas

---

## 7) Buenas prácticas / recomendaciones

* Mantener los ZIP en carpetas separadas (facturas vs notas de crédito)
* Revisar `errores.csv` cuando falte información o existan XML con estructura distinta
* Para auditoría de clasificación de productos:

  * usar `TokensStr`, `ProductoStd` y columnas derivadas del dim

---

## 8) Licencia

Uso académico / interno. Ajustar según necesidad del repositorio.

```
::contentReference[oaicite:0]{index=0}
```

