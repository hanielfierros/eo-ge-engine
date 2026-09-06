# S-A.16 — Raster Processing Report

- Fecha: 2026-09-06
- Motor: EO-GE Engine
- Fase: S-A.16 (JP2 → reflectancia → COG científico)
- Item fuente: `SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1`
- Producto fuente: `S2B_MSIL2A_20260828T174859_N0512_R141_T12RYP_20260828T213402`

---

## 1. Objetivo

Leer los JP2 reales B04/B08 (DN uint16), aplicar la máscara de nodata, convertir a
reflectancia superficial (`DN·0.0001 − 0.1`), generar productos raster científicos en
formato COG real, validarlos y registrarlos en el catálogo EO-GE, con trazabilidad
completa y sin modificar la fuente.

## 2. Inputs reales

| Campo | Valor |
|---|---|
| B04 fuente | `storage/normalized/.../files/B04_10m.jp2` (44 822 636 B) |
| B08 fuente | `storage/normalized/.../files/B08_10m.jp2` (47 052 534 B) |
| SHA-256 B04 | `bf94442d24e568e478290970a6037ea77c6af47e673cffb748cca36b17b18687` |
| SHA-256 B08 | `82395f6a56307a505d0e508b64a5ae679046cc879897ac1250ba574f7b29a970` |
| CRS nativo | EPSG:32612 |
| Resolución | 10 m |
| Dimensiones | 10980 × 10980 |
| dtype | uint16 |
| scale / offset | 0.0001 / −0.1 (L2A baseline ≥ 04.00) |
| DN == 0 | 62.6556 % (nadata/edge) |

Las fuentes se conservan **intactas** (SHA-256 idéntico antes y después).

## 3. Arquitectura utilizada

Se reutilizó la arquitectura existente; no se creó una paralela:

- `app/storage/local.py` (LocalDataStore) — ampliado con bucket `derived/`
  (`put_derived_metadata`, `put_derived_file`, `get_derived_file`,
  `verify_derived`, `exists_derived`, `delete_derived`). Mismas reglas de
  atomicidad, idempotencia, SHA-256 y path safety que `normalized/`.
- `app/catalog/catalog.py` (Catalog) — registro de los productos derivados.
- `app/geodata/interface.py` (GeoDataInterface) — lectura de fuente/metadata.
- `app/catalog/adapter.py` (`normalized_to_item`) — representación de catálogo.

Nuevo componente único: `app/processing/raster.py` (procesamiento raster).

## 4. Algoritmo

1. Lectura de la banda fuente (solo lectura, `rasterio.open`).
2. Construcción de máscara válida: `DN != 0`.
3. Conversión a reflectancia: `reflectance = DN·0.0001 − 0.1` (float32).
4. Aplicación de máscara: `DN == 0 → NaN`.
5. Escritura de COG real (GeoTIFF Cloud-Optimized).
6. Cálculo de SHA-256 del COG.
7. Construcción de metadata (contrato V1.0, `data_class = DERIVED_PRODUCT`).
8. Persistencia en `storage/derived/<id>/`.
9. Registro en catálogo.
10. Validación (geométrica, numérica, máscara, COG, integridad, catálogo).

## 5. Fórmula aplicada

```
reflectance = DN × 0.0001 − 0.1
```

- `scale = 0.0001`, `offset = −0.1` (correcto para Sentinel-2 L2A baseline ≥ 04.00).
- Valores de referencia: DN=1000 → 0.0; DN=10000 → 0.9; DN=11000 → 1.0.
- DN > 10000 es esperado (reflectancia > 0.9); NO se corrige ni se recorta.

## 6. Definición de máscara

- **Máscara válida**: `DN != 0`.
- **Nodata de salida**: `NaN` (float32).

Justificación del nodata `NaN`:
- **Valor elegido**: `NaN` (IEEE-754).
- **Razón**: la reflectancia es `float`; `DN=0` (nadata/edge) no debe mapear a un
  valor físico (DN=0 daría reflectancia −0.1, que parece válida). `NaN` es el nodata
  estándar e inequívoco para rasters float.
- **Impacto**: `NaN` propaga y se excluye automáticamente en reducciones
  (`np.nanmean`, masked arrays), obligando a enmascarar correctamente.
- **Compatibilidad con COG**: GDAL almacena el nodata `NaN` en el tag `GDAL_NODATA`
  del GeoTIFF float32 y lo recupera como `nan`.
- **Comportamiento de la máscara**: todo píxel con `DN==0` queda `NaN`; ningún píxel
  válido queda `NaN`.

En `metadata.json` el nodata se registra como `"nan"` (string) para mantener JSON
válido; en el COG es `NaN` float32.

## 7. Parámetros raster

| Parámetro | Valor |
|---|---|
| driver salida | COG (GeoTIFF Cloud-Optimized) |
| dtype salida | float32 |
| compresión | DEFLATE |
| blocksize | 512 × 512 |
| overviews internas | [2, 4, 8, 16, 32] |
| nodata | NaN |
| CRS | EPSG:32612 (conservado, sin reproyección) |
| transform | (10, 0, 699960, 0, −10, 2900040) |
| dimensiones | 10980 × 10980 |

## 8. Productos generados

| Producto | ID | Archivo | Tamaño | SHA-256 |
|---|---|---|---|---|
| B04 reflectancia | `SENTINEL2_..._T12RYP_B04_REFL_v1` | `derived/.../files/B04_10m_reflectance.tif` | 142 970 591 B | `a0fbadcb92e804d2af2e3c8a511578ac2a232d783f80e4286a1cd2b419a542d4` |
| B08 reflectancia | `SENTINEL2_..._T12RYP_B08_REFL_v1` | `derived/.../files/B08_10m_reflectance.tif` | 140 810 783 B | `1528c2b3d87ff7c0c97ae6cbe1e11661072d9d1b6d2010a9938bae46d39522b8` |

Cada producto conserva: source product/item, banda, datetime de adquisición, tile,
CRS, transform, resolución, dimensiones, dtype, scale/offset utilizados, máscara/nodata,
algoritmo, software/versión, SHA-256 y relación explícita con el JP2 fuente
(`provenance.parent_dataset`).

## 9. Validación geométrica

- CRS correcto (EPSG:32612): PASS.
- Transform correcto e idéntico a la fuente: PASS.
- Resolución 10 m: PASS.
- Dimensiones 10980 × 10980: PASS.
- Alineación exacta con la fuente (transform + dimensiones): PASS.
- Sin reproyección silenciosa: PASS.

## 10. Validación numérica

`reflectance == DN·0.0001 − 0.1` verificado (sin redondeo prematuro, tolerancia 1e-6):

- Píxeles de muestra deterministas (esquinas y centro): PASS
  (ej. B04 DN=1670 → 0.067; B08 DN=4198 → 0.3198).
- `DN == 0` → `NaN` (nadata): PASS.
- `DN == 11000` → 1.0: PASS (B04 @(420,3937); B08 @(412,3931)).
- `DN > 11000`: PASS — B04 max 17455 → 1.6455 @(2310,1574); B08 max 16801 → 1.5801 @(3191,714).
- `DN == 1000` y `DN == 10000`: **no presentes** en este raster real; su fórmula se
  verifica en la prueba unitaria `test_scale_offset_formula` (DN=0/1000/10000/11000/17455).

**Máscara** (idéntica en B04 y B08):

| Métrica | Valor |
|---|---|
| total de píxeles | 120 560 400 |
| píxeles válidos | 45 022 560 (37.3444 %) |
| píxeles inválidos (DN=0) | 75 537 840 (62.6556 %) |

Coherente con la auditoría previa (62.66 % de DN=0). Sin pérdida de cobertura
inesperada (válidos = píxeles sin NaN).

## 11. Validación COG

- Driver real GeoTIFF (COG): PASS.
- Tiling (bloques 512×512, `is_tiled`): PASS.
- Compresión DEFLATE: PASS.
- Overviews internas [2,4,8,16,32]: PASS.
- Georreferenciación (transform + CRS): PASS.
- Lectura correcta tras reabrir (dataset independiente): PASS.

## 12. Integridad / checksum

- SHA-256 de cada COG calculado y registrado en `manifest.json` y `metadata.json`
  (`data.storage.checksum`, `provenance.checksum`).
- `verify_derived()` devuelve `True` para ambos productos.
- Fuentes JP2 intactas (SHA-256 idéntico antes/después).

## 13. Tests ejecutados

Suite completa (existente + nueva), ejecutada **dos veces** (reproducibilidad):

```text
Ran 207 tests ... OK (skipped=1)
Ran 207 tests ... OK (skipped=1)
```

- Nueva suite `tests/test_raster_processing.py`: **17 tests** (fórmula scale/offset,
  DN=0, DN>10000, máscara, COG real, metadata, checksum, idempotencia, recuperación
  ante fallo, no modificación de fuente, ausencia de secretos, path safety).
- 1 skipped es el test de ingesta externa real (`TestRealIngestExternal`, por diseño).

## 14. Idempotencia

Reejecutar el procesamiento sobre los mismos inputs reutiliza el producto existente
(mismo SHA-256), **sin duplicar ni corromper**. Verificado con dos ejecuciones reales
sobre B04/B08 (mismo checksum, un único archivo por producto, `verify_derived` = True).

## 15. Limitaciones

- SCL (banda de clasificación de escena) sigue **no materializada**; la máscara usada
  es únicamente `DN==0` (nadata/edge), no una máscara de nubes/sombra.
- El `nodata` en `metadata.json` se representa como string `"nan"` (NaN no es JSON
  válido); el valor físico en el COG es `NaN` float32.
- No se calculan índices (NDVI/NDMI/NDWI/SAVI) en esta fase.
- El `scale/offset` de la banda de salida es `1.0/0.0` (el dato YA es reflectancia);
  el `scale/offset` de entrada (0.0001/−0.1) queda registrado en
  `provenance.transformations` y en `processing.transformations`.

## 16. Riesgos residuales

- Valores de reflectancia > 1 (DN > 11000) son esperados y NO enmascarados; deben
  tratarse según contexto (nube/nieve/glint) vía SCL cuando se materialice.
- Productos sobre OneDrive (carpeta sincronizada); el almacenamiento definitivo en
  backend dedicado (object storage/Zarr/PostGIS) es evolución futura.

## 17. Estado final de S-A.16

```
S-A.16 = READY_FOR_REVIEW
```

- Productos reales: 2 (B04 y B08 reflectancia COG).
- Validación: 22 checks por banda, todos PASS (44/44).
- Tests: 207 (OK, skipped=1), doble ejecución reproducible.
- Integridad: SHA-256 registrados y verificados; fuentes intactas.
- Catálogo: ambos productos registrados (data_class DERIVED_PRODUCT).
- Documentación: este reporte.

No se marcó `COMPLETED`; se requiere revisión (evidencia adjunta en
`reports/S_A16_RUN_RESULTS.json`).
