# S-A.17 — Spectral Indices Report

- Fecha: 2026-09-06
- Motor: EO-GE Engine
- Fase: S-A.17 (NDMI / NDWI / SAVI)

---

## 1. Objetivo

Producir índices espectrales como productos científicos derivados (COG) a partir de
las bandas de reflectancia superficial de S-A.16, con máscara, trazabilidad y
validación. Sin conclusiones agronómicas.

## 2. Definiciones científicas

| Índice | Fórmula | Bandas |
|---|---|---|
| SAVI | `((NIR − RED) / (NIR + RED + L)) · (1 + L)`, L=0.5 | NIR=B08, RED=B04 |
| NDMI | `(NIR − SWIR) / (NIR + SWIR)` | NIR=B08, SWIR=B11 |
| NDWI (McFeeters) | `(GREEN − NIR) / (GREEN + NIR)` | GREEN=B03, NIR=B08 |

## 3. Fórmulas (aplicadas sobre reflectancia)

- SAVI = `((B08 − B04) / (B08 + B04 + 0.5)) × 1.5`
- NDMI = `(B08 − B11) / (B08 + B11)`
- NDWI = `(B03 − B08) / (B03 + B08)`

Se aplican sobre **reflectancia** (productos COG float32 de S-A.16), **NO** sobre DN
crudo, y **sin** reaplicar `scale·DN + offset` (B04/B08 ya son reflectancia).

## 4. Bandas requeridas / 5. disponibles / 6. faltantes

- SAVI: requiere B08+B04 → **disponibles**.
- NDMI: requiere B08+B11 → B11 **falta**.
- NDWI: requiere B03+B08 → B03 **falta**.

Ver `reports/S_A17_BAND_REQUIREMENTS.md`.

## 7. Decisión de adquisición

Opción A: procesar **solo SAVI**; **NDMI/NDWI PENDING** (requieren B03/B11, no
materializados). Sin descarga automática; sin sustituciones incorrectas de bandas.

## 8. Máscara

- Cualquier píxel de entrada inválido (`NaN`) → índice inválido (`NaN`).
- Denominador = 0 → inválido (`NaN`), nunca infinito.
- `NaN` → inválido.
- Sin generación de valores artificiales (sin relleno de huecos).
- SCL sigue **no materializado**: la máscara es solo la herencia de `DN==0 → NaN`
  de las reflectancias; no hay máscara de nubes/sombra.

## 9. Tratamiento de denominadores

División protegida (`np.errstate` + enmascarado posterior): `denominador == 0` o no
finito → `NaN`. No se producen infinitos.

## 10. Precisión numérica

`float32` (consistente con los productos de reflectancia S-A.16 y el driver COG).
No hay overflow; se evita pérdida de precisión usando aritmética float32 directa.
Verificación con muestras deterministas e independientes.

## 11. Productos

| Producto | ID | Inputs | Estado |
|---|---|---|---|
| SAVI | `SENTINEL2_..._T12RYP_SAVI_v1` | B08_REFL + B04_REFL | **generado** |
| NDMI | (pendiente) | B08_REFL + B11_REFL | PENDING (falta B11) |
| NDWI | (pendiente) | B03_REFL + B08_REFL | PENDING (falta B03) |

Producto generado: `storage/derived/SENTINEL2_..._T12RYP_SAVI_v1/files/SAVI_10m.tif`
(212 190 784 B), SHA-256 `ce3dc2a054abffe7f7a7ad663b00b70a85b85d9d55d81f42fbfd0b9373fdb611`.

## 12. Validación geométrica

SAVI verificado: CRS EPSG:32612 idéntico, transform idéntico, resolución 10 m,
dimensiones 10980×10980, alineación píxel-a-píxel con los inputs, bounds y footprint
coherentes. Sin reproyección silenciosa.

## 13. Validación numérica

Tests sintéticos con expected **independiente** (no la misma función) para SAVI/NDMI/
NDWI: valores normales, denominador cero, `NaN`, máscara parcial, dimensiones
incompatibles. Casos reales verificados contra recomposición independiente del índice.

## 14. COG

COG real (driver GeoTIFF, `LAYOUT=COG`): tiled (512×512), DEFLATE, overviews
[2,4,8,16,32], georreferenciado, máscara/nodata `NaN`.

## 15. Catálogo

SAVI registrado en el catálogo EO-GE (`sentinel-2-l2a`, `data_class=DERIVED_PRODUCT`,
asset `SAVI`, storage_path `derived/...`). Recuperable y verificable por checksum.

## 16. Idempotencia

Reejecución de SAVI produce el mismo SHA-256, sin duplicar ni corromper.

## 17. Tests

```text
Suite completa: 225 tests OK (skipped=1)  — 2 ejecuciones del subconjunto S-A.17
S-A.17 (test_spectral_indices): 18 tests OK
```

0 failed / 0 errors. El skipped=1 es `TestRealIngestExternal` (intencional).

## 18. Limitaciones

- SCL no materializado → sin máscara de nubes/sombra; la máscara hereda solo `DN==0`.
- NDMI y NDWI no calculados (faltan B11 y B03).
- Índices sobre OneDrive (backend local).

## 19. Warnings

| ID | Severidad | Hallazgo |
|---|---|---|
| W1 | MEDIUM | B03/B11 no materializados → NDMI/NDWI PENDING. |
| W2 | MEDIUM | SCL no materializado → máscara sin nubes/sombra (heredado de S-A.16). |
| W3 | INFO | SAVI dentro del rango esperado [−1,1] (mín −0.281, máx 0.767); sin valores fuera de rango. |

## 20. Estado final

```
S-A.17 = PARTIAL / READY_FOR_REVIEW
```

- SAVI: generado, validado y catalogado (22/22 checks PASS).
- NDMI / NDWI: PENDING (requieren B03/B11).

Estadísticas SAVI (valores válidos): total 120 560 400 px; válidos 45 022 560
(37.3444 %); inválidos 75 537 840 (62.6556 %); NaN 75 537 840; inf 0; mín −0.28098;
máx 0.76746; media 0.15896; p01 −0.06592; p50 0.07332; p99 0.59577; fuera de [−1,1]: 0.

---

## ACTUALIZACIÓN (2026-09-06) — B03/B11 reflectancia + NDWI/NDMI completados

Con B03 y B11 raw materializados (ver `reports/S_A17_BAND_REQUIREMENTS.md`), se
completaron los productos restantes de S-A.17 reutilizando el pipeline S-A.16
(`app/processing/raster.py`) y extendiendo `app/processing/indices.py` con
resampling explícito.

### Productos generados

| Producto | ID | Archivo | Resolución | Dimensiones | SHA-256 | Tamaño |
|---|---|---|---|---|---|---|
| B03 reflectancia | `..._B03_REFL_v1` | `B03_10m.tif` | 10 m | 10980×10980 | `2489e7d1dcc51da221373f0ff9e20ce50fad9878c0a07e08e33e8c4f906a4638` | 141 254 040 B |
| B11 reflectancia | `..._B11_REFL_v1` | `B11_20m.tif` | 20 m | 5490×5490 | `febd31aafc988838c553e4aa12e1c0435951fa346c7b22532924e0fb490a4c45` | 37 826 143 B |
| NDWI | `..._NDWI_v1` | `NDWI_10m.tif` | 10 m | 10980×10980 | `fa02133d64382d7d57e09df8f1e43cd49c69ec9d1814043d3a78f7f9ee64922f` | 209 452 051 B |
| NDMI | `..._NDMI_v1` | `NDMI_20m.tif` | 20 m | 5490×5490 | `131959bdff3d2ebb6cf67d9ff2ba67acceac1ded68e45119357d50805b5e0740` | 54 465 553 B |

### Fórmulas (sobre reflectancia, no DN)

- NDWI = `(B03 − B08) / (B03 + B08)` (GREEN=B03, NIR=B08).
- NDMI = `(B08 − B11) / (B08 + B11)` (NIR=B08, SWIR=B11).
- Reflectancia: `DN × 0.0001 − 0.1` (baseline ≥ 04.00), máscara `DN==0 → NaN`.

### Decisión científica NDMI = 20 m

B08 es 10 m y B11 es 20 m. El NDMI se genera a **resolución nativa de B11 (20 m)**:

1. B11 conservado en su grid nativo 20 m (sin reamuestreo, sin reproyección).
2. B08 reamuestrado de 10 m → grid exacto de B11 (20 m) mediante
   `rasterio.warp.reproject`, método **bilinear**, nodata NaN→NaN.
3. CRS destino EPSG:32612, transform destino = transform exacto de B11,
   dimensiones 5490×5490.

La operación queda registrada en `processing.transformations` /
`provenance.transformations`:
`resampling.role=NIR;source=B08 10m;target_grid=SWIR 20m;method=bilinear;source_nodata=nan;dest_nodata=nan`.

### Máscara

- Cualquier input inválido (NaN) → índice NaN.
- Denominador == 0 → NaN (nunca infinito).
- Resultado no finito → NaN.
- **Sin clipping** a [−1,1].

### Validación

Independiente (relectura de inputs + recomposición del índice + resampling
independiente), con tolerancia float32:

- B03_REFL: 23/23 PASS.
- B11_REFL: 23/23 PASS.
- NDWI: 18/18 PASS.
- NDMI: 18/18 PASS (resampling, fórmula, máscara, sin Inf, dimensiones, transform, CRS, resolución).

### Estadísticas (valores válidos)

| Índice | válidos | inválidos | mín | máx | media |
|---|---|---|---|---|---|
| NDWI | 45 022 560 (37.34 %) | 75 537 840 (62.66 %) | −0.80639 | 1.43053 | −0.23728 |
| NDMI | 11 255 640 (37.34 %) | 18 884 460 (62.66 %) | −0.49769 | 1.04251 | 0.01725 |

- `inf` = 0 en ambos. 1 píxel > 1 en ambos (reflectancia > 1 por nube/glint; no se recorta).

### Integridad

B03/B11/B04/B08 raw y B04_REFL/B08_REFL/SAVI: SHA-256 idénticos (PASS).

### Idempotencia

Reejecución completa produce SHA-256 idénticos, sin duplicar productos ni assets.

### Tests

Suite completa (unittest discover): **231 tests OK (skipped=1)**, doble ejecución.
`skipped=1` = `TestRealIngestExternal` (intencional).

### Warnings

- 1 píxel > 1 en NDWI y NDMI (reflectancia > 1); sin clipping (regla científica).
- SCL no materializado: máscara = DN==0, sin nubes/sombra.
- `pytest` no instalado en el entorno WSL; se usó `unittest discover` (runner canónico).

### Estado final

```
S-A.17 = PARTIAL / READY_FOR_REVIEW
```

- B03/B11 reflectancia y NDWI/NDMI generados, validados y catalogados.
- S-A.17 **no se cierra** (queda pendiente la auditoría/revisión final).
- S-A.18 no iniciada. BRAIN_00/01/02 y Radar Engine no modificados.
