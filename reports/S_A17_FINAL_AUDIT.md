# S-A.17 — Final Audit

- Fecha: 2026-09-06
- Motor: EO-GE Engine
- Fase: S-A.17 (NDMI / NDWI / SAVI) — auditoría final
- Alcance: auditoría técnica y científica de los productos S-A.17 (B03_REFL, B11_REFL, NDWI, NDMI) y de los cambios de código introducidos. Solo auditoría: no se realizaron adquisiciones, no se modificaron productos, no se inició S-A.18, no se hizo commit/push.

---

## 1. Alcance

Auditar de forma independiente:

- Productos B03_REFL, B11_REFL, NDWI, NDMI (integridad, raster, COG, catálogo, metadata).
- Ciencia (fórmula reflectancia, DN=0→NaN, fórmulas NDWI/NDMI).
- NDWI (grid 10 m, sin resampling).
- NDMI (grid 20 m, reamuestreo bilinear explícito B08→B11).
- Máscara, pixel >1, SCL, tests, regresión, idempotencia, código, seguridad.

## 2. Productos auditados

| Producto | Archivo | SHA-256 | Match | Tamaño |
|---|---|---|---|---|
| B03_REFL | `B03_10m.tif` | `2489e7d1dcc51da221373f0ff9e20ce50fad9878c0a07e08e33e8c4f906a4638` | PASS | 141 254 040 B |
| B11_REFL | `B11_20m.tif` | `febd31aafc988838c553e4aa12e1c0435951fa346c7b22532924e0fb490a4c45` | PASS | 37 826 143 B |
| NDWI | `NDWI_10m.tif` | `fa02133d64382d7d57e09df8f1e43cd49c69ec9d1814043d3a78f7f9ee64922f` | PASS | 209 452 051 B |
| NDMI | `NDMI_20m.tif` | `131959bdff3d2ebb6cf67d9ff2ba67acceac1ded68e45119357d50805b5e0740` | PASS | 54 465 553 B |

Los 4 SHA-256 coinciden con los documentados. No hay corrupción.

## 3. Validación raster (Rasterio)

| Producto | driver | CRS | res | dims | dtype | nodata | tiled | compresión | overviews |
|---|---|---|---|---|---|---|---|---|---|
| B03_REFL | GTiff (COG) | EPSG:32612 | 10 m | 10980×10980 | float32 | NaN | 512×512 | DEFLATE | [2,4,8,16,32] |
| B11_REFL | GTiff (COG) | EPSG:32612 | 20 m | 5490×5490 | float32 | NaN | 512×512 | DEFLATE | [2,4,8,16] |
| NDWI | GTiff (COG) | EPSG:32612 | 10 m | 10980×10980 | float32 | NaN | 512×512 | DEFLATE | [2,4,8,16,32] |
| NDMI | GTiff (COG) | EPSG:32612 | 20 m | 5490×5490 | float32 | NaN | 512×512 | DEFLATE | [2,4,8,16] |

Transform: B03/B04/B08/NDWI = `[699960,10,0,2900040,0,-10]`; B11/NDMI = `[699960,20,0,2900040,0,-20]`.
Bounds coherentes (699960, 2790240, 809760, 2900040). COG real.

## 4. Validación científica B03/B11

- B03 = GREEN, 10 m, EPSG:32612 — confirmado.
- B11 = SWIR, 20 m, EPSG:32612 — confirmado.
- `reflectance = DN × 0.0001 − 0.1` aplicada exactamente una vez (raw JP2 → COG float32 vía `derive_band_reflectance`). No se reaplica scale/offset.
- `DN == 0 → NaN` (máscara nodata/edge). Sin clipping de reflectancia.

## 5. NDWI

- Fórmula: `(GREEN − NIR) / (GREEN + NIR)` = `(B03 − B08) / (B03 + B08)`.
- Entradas: B03_REFL y B08_REFL, ambas 10 m, EPSG:32612, misma dimensión (10980×10980), mismo transform, mismo grid.
- **Sin resampling ni reproyección** (`derive_index_product` rechaza inputs geométricamente incompatibles).
- Denominador == 0 → NaN; NaN propagado; sin Inf (inf_count = 0).
- Validación numérica independiente (relectura + fórmula manual en numpy, sin usar la función de producción): `max_abs_diff = 1.19e-7` (float32). PASS.

## 6. NDMI — crítica

- Fórmula: `(NIR − SWIR) / (NIR + SWIR)` = `(B08 − B11) / (B08 + B11)`.
- Entradas: B08_REFL (10 m), B11_REFL (20 m).
- **Producto final = 20 m** (grid nativo de B11).
- B11 permanece en su grid nativo (no reamuestrado, no reproyectado).
- B08 transformado explícitamente al grid de B11 mediante `rasterio.warp.reproject`, `Resampling.bilinear`, CRS EPSG:32612, transform destino = transform exacto de B11, 5490×5490, source/dest nodata = NaN.
- Provenance registra la transformación:
  `resampling.role=NIR;source=B08 10m;target_grid=SWIR 20m;method=bilinear;source_nodata=nan;dest_nodata=nan`.
- Validación numérica independiente (relectura + `rasterio.warp.reproject` directo + fórmula manual en numpy): `max_abs_diff = 0.0`, máscara coherente, sin Inf. PASS.

## 7. Máscara

- NDWI válido = B03 válido AND B08 válido.
- NDMI válido = B08 válido AND B11 válido.
- NaN propagado correctamente; denominador == 0 → NaN; resultado no finito → NaN; sin clipping.

## 8. Auditoría del píxel > 1

Se investigó sin modificar el producto.

| Producto | Píxel | Coordenada (UTM 12N) | Valor | Entradas | Cálculo manual | Coincide |
|---|---|---|---|---|---|---|
| NDWI | [812, 2541] | (725375, 2891915) | 1.43053 | B03=0.0621, B08=−0.0110 | 1.43053 | Sí |
| NDMI | [3449, 578] | (711530, 2831050) | 1.04251 | B08_20m=0.1874, B11=−0.0039 | 1.04251 | Sí |

**Conclusión**: los valores >1 son matemáticamente correctos. Se deben a reflectancias ligeramente negativas (B08/B11 con DN < 1000 → `DN·0.0001 − 0.1 < 0`) combinadas con denominador positivo pequeño. No es un error de procesamiento. Se mantienen sin clipping. Documentado como warning científico.

## 9. SCL

- SCL no materializado — confirmado.
- La máscara actual está basada únicamente en `DN == 0` (nadata/edge).
- Los productos **no** declaran máscara de nubes/sombra; no hay afirmación falsa.
- No existía especificación previa que exigiera SCL obligatorio para liberar S-A.17.
- Clasificación: **WARNING** (no afecta la validez matemática). SCL no se materializa en esta auditoría.

## 10. Catálogo

- 8 items `sentinel-2-l2a` (raw, B04_REFL, B08_REFL, SAVI, B03_REFL, B11_REFL, NDWI, NDMI).
- Sin assets duplicados.
- Productos nuevos presentes; productos anteriores intactos.

## 11. Regresión

| Producto | SHA-256 | Estado |
|---|---|---|
| B03 raw | `895d747e…94e57` | PASS |
| B11 raw | `7cd433ef…6989` | PASS |
| B04 raw | `bf94442d…b18687` | PASS |
| B08 raw | `82395f6a…9a970` | PASS |
| B04_REFL | `a0fbadcb…a542d4` | PASS |
| B08_REFL | `1528c2b3…522b8` | PASS |
| SAVI | `ce3dc2a0…fdb611` | PASS |

Todos intactos (SHA-256 idénticos a los documentados).

## 12. Idempotencia

La implementación es determinista: reejecución produce el mismo SHA-256 y reutiliza el producto existente (`store.exists_derived` + comparación de SHA) sin duplicar assets ni entradas de catálogo. Verificado con doble ejecución real en la fase de generación.

## 13. Auditoría de código (cambios S-A.17)

Revisados: `app/processing/raster.py`, `app/processing/indices.py`, `tests/test_raster_processing.py`, `tests/test_spectral_indices.py`.

- **Sin secretos/tokens/passwords** en código, metadata ni reportes.
- **Sin rutas absolutas hardcodeadas** en el código de producción (se usan `store`/`catalog`/`geo`).
- **Sin dependencias nuevas**: `rasterio.warp` es parte de `rasterio==1.5.1` (ya en requirements).
- **Sin resampling/reproyección implícita**: solo `derive_resampled_index` reamuestra (bilinear explícito); `derive_index_product` rechaza grids distintos; no hay reproyección de CRS (EPSG:32612 conservado).
- **Sin pérdida de metadata**: source/acquisition/spatial/provenance conservados; la transformación queda en `processing.transformations` y `provenance.transformations`.
- **Sin modificaciones destructivas**: fuentes solo lectura; escritura atómica en `derived/`.
- **Determinismo**: idempotencia por comparación de SHA.

Hallazgo menor (no bloqueante):

- **LOW** — `derive_index_product` (índices same-grid) genera nombre `_10m.tif` y resolución 10 m por defecto hardcodeados. Correcto para NDWI/SAVI (10 m); no generalizable sin parámetro para un índice same-grid de otra resolución. No es defecto para el alcance S-A.17.

## 14. Tests

```text
RUN 1: python -m unittest discover -s tests -p 'test_*.py' -v
  Ran 231 tests in 50.9s — OK (skipped=1)
RUN 2: python -m unittest discover -s tests -p 'test_*.py' -v
  Ran 231 tests in 41.8s — OK (skipped=1)
```

- 0 failed, 0 errors.
- `skipped=1` = `TestRealIngestExternal` (ingesta externa CDSE, intencional y documentado).
- `pytest` no está instalado; `unittest discover` es el runner canónico del proyecto (README). No se considera la ausencia de pytest como fallo.

## 15. Clasificación de hallazgos

| ID | Severidad | Hallazgo |
|---|---|---|
| F1 | MEDIUM | SCL no materializado → máscara solo DN==0 (sin nubes/sombra). Documentado; no bloquea. |
| F2 | MEDIUM | 1 píxel >1 en NDWI y NDMI (reflectancias negativas L2A). Matemáticamente correcto; sin clipping; documentado. |
| F3 | LOW | `derive_index_product` hardcodea `_10m.tif` (correcto para índices 10 m; no generalizable). |
| F4 | INFO | pytest ausente; runner canónico = unittest discover. |

- CRITICAL: 0
- HIGH: 0
- MEDIUM: 2
- LOW: 1
- INFO: 1

## 16. Clasificación final

```
S-A.17 = APPROVED_WITH_WARNINGS
```

- Integridad, hashes, ciencia, NDWI, NDMI (resampling explícito bilinear), provenance, catálogo, COG, tests y regresión: **PASS**.
- Sin defectos CRITICAL ni HIGH. Solo warnings conocidos y documentados (SCL, valores >1 explicados, pytest ausente).
- Recomendación: **RELEASE** (S-A.17 apta para release), pero la auditoría termina aquí; NO se hace commit/push/release ni se inicia S-A.18.
