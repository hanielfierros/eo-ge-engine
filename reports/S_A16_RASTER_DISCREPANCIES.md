# S-A.16 — Resolución de Discrepancias Raster

- Fecha: 2026-09-06
- Motor: EO-GE Engine
- Fase: S-A.16 (investigación/validación local, sin procesamiento)
- Item: `SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1`
- Producto: `S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402`

La auditoría raster previa B04/B08 fue **PASS** (alineados espacialmente píxel-a-píxel:
10980×10980, uint16, EPSG:32612, transform/bounds/resolución idénticos). Se confirman dos
discrepancias entre la metadata EO-GE registrada y el raster físico. Este reporte documenta
cómo debe resolverse cada una **científicamente**, sin modificar código, metadata, JP2 ni
generar productos.

---

## Discrepancia 1 — `nodata`

### Hallazgo

| Fuente | Valor |
|---|---|
| `metadata.json` (`data.raster.bands[].nodata`) | `0` |
| Raster físico (JP2, vía Rasterio) | `None` (sin nodata embebido) |
| Píxeles DN = 0 | B04 = 62.6556 %, B08 = 62.6556 % |

La metadata declara `nodata = 0`, pero el archivo JP2 real no lleva nodata incrustado
(`ds.nodata = None`, `ds.nodatavals[0] = None`).

### Evidencia

1. `storage/normalized/.../metadata.json` → `data.raster.bands[].nodata = 0` (B04 y B08).
2. Auditoría Rasterio (B04/B08): `nodata (dataset) = None`, `nodata (band) = None`.
3. `reports/S_A15_SENTINEL2_INGESTION_REPORT.md` (tabla "Asset"): `nodata = 0` (declarado, **no aplicado**).
4. `tests/fixtures/sentinel2_source_representation.json` → `collection_metadata.*.nodata = 0`.
5. `app/normalizers/sentinel2.py` (`_build_bands`): `"nodata": ca.get("nodata")` — proviene del
   `item_assets` de la colección STAC CDSE, no del archivo físico.

Conclusión: `nodata = 0` es una **declaración de la colección STAC** (convención oficial ESA),
no un valor incrustado en el JP2.

### ¿Puede tratarse DN = 0 como máscara inválida para este producto?

**Sí, con justificación** (no por mera suposición):

1. La colección STAC CDSE declara `nodata = 0` para las bandas de reflectancia L2A.
2. La combinación `scale = 0.0001`, `offset = -0.1` (baseline >= 04.00) implica
   `reflectancia = DN · 0.0001 − 0.1`. Para DN = 0 la reflectancia resultante es **−0.1**,
   físicamente imposible ⇒ DN = 0 queda fuera del rango físico válido y corresponde a
   nodata/edge (fuera de la huella útil del granule).
3. El 62.6556 % de píxeles en 0 es consistente con la geometría de huella del granule: la huella
   válida es un polígono no rectangular dentro del tile 10980×10980; el resto del rectángulo se
   rellena con 0. Esto es esperable para un granule en el borde del barrido orbital.

**Caveat científico**: no se afirma que *todo* DN = 0 sea "inválido" en cualquier producto
Sentinel-2; la afirmación es específica de este producto L2A y de estas bandas de reflectancia,
sustentada en la declaración `nodata = 0` de la colección y en el offset de −0.1.

### Información de máscara / validity / footprint disponible

- **Footprint (vectorial):** SÍ. `metadata.json → spatial.footprint` es un `Polygon` GeoJSON (la
  huella válida del granule en WGS84 lon/lat).
- **Máscara a nivel de píxel (SCL):** DECLARADA (`data.raster.qa_band = "SCL"`,
  `cloud_mask = "SCL"`) pero **NO materializada** localmente (solo existen `B04_10m.jp2` y
  `B08_10m.jp2`; no hay `SCL_20m.jp2`).

### Impacto científico

- Si en S-A.16 se lee el raster sin aplicar la máscara de nodata, los 62.66 % de píxeles en 0
  contaminarían cualquier estadística o índice (NDVI/NDMI/NDWI/SAVI) con valores espurios
  (p. ej. NDVI con reflectancia nula). Esto invalidaría el producto derivado.
- La ausencia de nodata embebido en el JP2 hace que una lectura "ingenua" de Rasterio trate 0
  como dato válido.

### Decisión recomendada

1. **Conservar** `nodata = 0` en `metadata.json` (es científicamente correcto y trazable a la
   colección STAC). NO cambiar el valor.
2. **NO** reescribir los JP2 para incrustar nodata (violaría "no modificar los JP2 originales"
   y no es necesario).
3. En el procesamiento S-A.16, aplicar la máscara `DN == 0` como nodata **a partir de la
   declaración de la metadata** (no del encabezado del archivo). Documentar esta decisión en
   `provenance`/`processing` del producto derivado.

### Decisión NO tomada (requiere fase posterior)

- **Materialización del SCL** (`SCL_20m.jp2`) como máscara de validez/calidad a nivel de píxel
  (clases: NO_DATA, cloud, shadow, etc.). Hoy está declarada pero ausente; su adquisición y
  normalización corresponde a una fase posterior (no a esta).

---

## Discrepancia 2 — `format` (COG vs JP2)

### Hallazgo

| Fuente | Valor |
|---|---|
| `metadata.json` (`data.storage.format`) | `COG` |
| `manifest.json` (`files.*.format`) | `JP2` |
| Raster físico (Rasterio) | driver `JP2OpenJPEG`, extensión `.jp2` |

### Evidencia

1. `storage/normalized/.../metadata.json` → `data.storage.format = "COG"`.
2. `storage/normalized/.../manifest.json` → `format = "JP2"` (B04 y B08).
3. Auditoría Rasterio: driver `JP2OpenJPEG`.
4. `app/normalizers/sentinel2.py` (línea 203): `"format": "COG"` (declaración fija del
   normalizador).
5. `docs/EO_GE_SENTINEL2_NORMALIZER.md` (Limitaciones): *"`storage.format = "COG"` es una
   declaración de formato canónico (S-A.2); la materialización real ocurre en S-A.9."*
6. `docs/EO_GE_NORMALIZED_DATA_CONTRACT_V1.md` §20: *"El contrato no acopla a SQLite, COG,
   Zarr, GeoParquet ni PostGIS (decisiones de implementación del Data Store, S-A.2)."*

### Interpretación

No es un error de datos; es una **separación arquitectónica explícita**:

- **SOURCE REPRESENTATION:** el JP2 original de Sentinel-2 (formato nativo del proveedor).
- **NORMALIZED / SCIENTIFIC PRODUCT:** el COG canónico declarado para raster 2D (objetivo de
  normalización/almacenamiento).

El `storage.format = "COG"` es una **declaración de formato canónico objetivo**. La
materialización real a COG ocurre en **S-A.9** (Data Store), que aún no se ha ejecutado. Por eso
los archivos físicos en `normalized/files/` siguen siendo JP2 (copia del source, estadificada de
forma atómica e idempotente).

El par `metadata.json` (declaración canónica) + `manifest.json` (formato físico real `JP2`)
**ya reconcilia** la discrepancia: el manifiesto registra la verdad física.

### Impacto científico

- Ninguno sobre los valores radiométricos: los JP2 son los originales íntegros (SHA-256 y
  sha3-256 CDSE verificados). El `format` solo describe el contenedor.
- Riesgo de confusión si un consumidor asume que el archivo es un COG (tiles/overviews
  optimizados) cuando aún es JP2. El JP2 tiene `block_shapes (1024,1024)` y overviews
  `[2,4,8,16]`, pero no es un COG georreferenciado en GeoTIFF.

### Decisión recomendada

1. **NO convertir** los JP2 a COG ahora (eso es S-A.9, fase posterior).
2. Tratar `storage.format = "COG"` como **formato canónico objetivo** (declaración S-A.2),
   coherente con el contrato V1.0 (que no acopla formato físico).
3. Mantener `manifest.json` con `format = "JP2"` como registro de la realidad física.
4. (Opcional, fase posterior) Aclarar en `metadata.json` que el archivo físico sigue siendo JP2
   mientras S-A.9 no lo materialice como COG; NO es necesario para S-A.16.

### Decisión NO tomada (requiere fase posterior)

- **Materialización COG real** de B04/B08 (S-A.9 / Data Store). Depende de una fase posterior
  y no es prerrequisito del cálculo de índices en S-A.16.

---

## Confirmación `scale` / `offset`

**Confirmado, sin modificar.**

| Parámetro | Valor | Fuente local |
|---|---|---|
| `scale` | `0.0001` | `metadata.json`, `fixture sentinel2_source_representation.json` (`collection_metadata.raster:scale`), `S_A15 report` |
| `offset` | `-0.1` | `metadata.json`, `fixture ...` (`raster:offset`), `S_A15 report` |

- El normalizador (`app/normalizers/sentinel2.py`) toma `scale`/`offset` del `item_assets` de la
  colección STAC CDSE (`raster:scale`, `raster:offset`), no los inventa.
- Combinación `scale = 0.0001`, `offset = -0.1` es **correcta para Sentinel-2 L2A baseline
  >= 04.00** (`reflectancia = DN · 0.0001 − 0.1`). **NO cambiar offset a 0.0.**
- Nota: `contracts/examples/sentinel2_l2a.json` muestra `offset = 0.0` y `EPSG:32613`; es un
  **ejemplo histórico desactualizado** (misma convención vieja que el fixture con EPSG
  incorrecto). No es autoritativo para el producto real (T12RYP → EPSG:32612, offset −0.1).

---

## Rangos — DN máximos > 10000

### Hallazgo

- B04: min DN = 0, max DN = **17455**
- B08: min DN = 0, max DN = **16801**

### ¿Son posibles/esperables valores > 10000 bajo la convención L2A?

**Sí, son esperables** (no es un error ni requiere corrección automática).

Con `scale = 0.0001`, `offset = -0.1`:

| DN | Reflectancia (= DN·0.0001 − 0.1) |
|---|---|
| 0 | −0.1 (nadata) |
| 1000 | 0.0 |
| 10000 | 0.9 |
| 11000 | 1.0 (100 %) |
| 17455 | 1.6455 |
| 16801 | 1.5801 |

El rango físico [0, 1] de reflectancia mapea a **DN [1000, 11000]**. Por tanto, DN > 10000 es
**normal** para cualquier píxel por encima del 90 % de reflectancia, y DN > 11000 corresponde a
reflectancia > 100 %, que puede ocurrir en blancos brillantes (nubes, nieve, glint especular),
sobre-corrección BRDF o efectos de adyacencia. Es una característica del producto, no un defecto.

### Manejo científico recomendado

1. **NO recortar ni "corregir"** los DN máximos automáticamente (violaría la regla de no alterar
   los valores originales y destruiría información radiométrica).
2. Tratar los valores > 11000 como reflectancia alta válida, y segregar las clases de nube/nieve/
   no-dato mediante el SCL (pendiente de materialización) — no por umbral arbitrario de DN.
3. En el cálculo de índices (S-A.16 posterior), dejar que el numerador/denominador reflejen el
   rango real (incluyendo reflectancias > 1) sin clipping, salvo que un requisito científico
   específico lo exija (entonces documentarlo).

### Decisión NO tomada (requiere fase posterior)

- Política de umbrales/clipping y uso del SCL para enmascarar blancos brillantes durante el
  cálculo de índices — se definirá en la fase de procesamiento científico.

---

## Resumen

| # | Discrepancia | Resolución |
|---|---|---|
| 1 | `nodata`: metadata `0` vs JP2 `None` | Declaración STAC correcta; aplicar máscara `DN==0` desde metadata en S-A.16; NO reescribir JP2. |
| 2 | `format`: metadata `COG` vs JP2 real | Declaración de formato canónico (S-A.2); materialización COG = S-A.9 (posterior); manifest ya registra `JP2`. |
| — | `scale`/`offset` | Confirmado `0.0001` / `-0.1` (correcto baseline >= 04.00). NO cambiar. |
| — | DN > 10000 | Esperable (offset −0.1 desplaza reflectancia 0.9→DN 10000, 1.0→DN 11000). NO corregir. |

**No se modificó código, ni `metadata.json`, ni los JP2, ni se generaron productos.**

DETENIDO.
