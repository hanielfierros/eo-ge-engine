# S-A.16 — Final Audit

- Fecha: 2026-09-06
- Motor: EO-GE Engine
- Fase: S-A.16 (auditoría final previa a commit/push)

---

## 1. Scope

Auditoría final de EO-GE S-A.16 (JP2 B04/B08 → reflectancia → COG científico),
incluyendo producto científico, contrato, COG, nodata/máscara, seguridad,
reproducibilidad, regresión e integridad de fuentes. Solo auditoría: no se
continuó a S-A.17, no se generaron índices, no se modificaron BRAIN_00/01 ni
Radar Engine, no se descargaron datos y los JP2 originales no se tocaron.

## 2. Estado inicial

`S-A.16 = READY_FOR_REVIEW` (resultado del procesamiento). Git DIRTY. NO commit.
NO push.

## 3. Cambios auditados

| Clase | Archivo | Naturaleza |
|---|---|---|
| Científico | `app/processing/__init__.py`, `app/processing/raster.py` | Nuevo: procesamiento raster (lectura, máscara, scale/offset, COG, metadata, catálogo) |
| Científico | `tests/test_raster_processing.py` | Nuevo: 17 tests (fórmula, DN=0, DN>10000, máscara, COG, metadata, idempotencia, seguridad, path safety) |
| Infraestructura | `app/storage/local.py` | Extensión: bucket `derived/` (solo adiciones, +114 líneas; sin cambios a métodos existentes) |
| Dependencias | `requirements.txt` | `rasterio==1.5.1` (cambio previo a S-A.16; no se elimina — justificado) |
| Gitignore | `.gitignore` | `+.venv-wsl/` |
| Documentación | `reports/S_A16_RASTER_DISCREPANCIES.md`, `reports/S_A16_RASTER_PROCESSING_REPORT.md`, `reports/S_A16_RUN_RESULTS.json` | Evidencia |

Artefactos locales correctamente ignorados: `.venv-wsl/`, `storage/` (incluido
`storage/derived/` y `storage/source_cache/`), `catalog/`, `*.sqlite`, `__pycache__/`.

## 4. Productos auditados

| Producto | ID | Archivo | SHA-256 |
|---|---|---|---|
| B04 reflectancia COG | `SENTINEL2_..._T12RYP_B04_REFL_v1` | `storage/derived/.../B04_10m_reflectance.tif` (142 970 591 B) | `a0fbadcb92e804d2af2e3c8a511578ac2a232d783f80e4286a1cd2b419a542d4` |
| B08 reflectancia COG | `SENTINEL2_..._T12RYP_B08_REFL_v1` | `storage/derived/.../B08_10m_reflectance.tif` (140 810 783 B) | `1528c2b3d87ff7c0c97ae6cbe1e11661072d9d1b6d2010a9938bae46d39522b8` |

## 5. Validación científica

Fórmula verificada de forma independiente: `reflectance = DN × 0.0001 − 0.1`.

| Caso | Resultado |
|---|---|
| DN=0 → NaN (inválido) | PASS |
| DN=1000 → 0.0 | no presente en la escena; verificado en unit test `test_scale_offset_formula` |
| DN=10000 → 0.9 | no presente en la escena; verificado en unit test |
| DN=11000 → 1.0 | PASS (B04 @(420,3937); B08 @(412,3931)) |
| DN>11000 → >1.0 | PASS (B04 DN=11010→1.001; B08 DN=11059→1.0059) |

**Por qué valores >1 permanecen**: la reflectancia L2A puede superar 1.0 en blancos
brillantes (nubes, nieve, glint), sobre-corrección BRDF o adyacencia. Son
observaciones radiométricas válidas que deben **interpretarse** (vía SCL u otro
máscara) en etapas posteriores, no **eliminarse** durante esta etapa. No se impuso
reflectancia máxima ni se recortó nada.

## 6. Validación raster

Para B04 y B08 (independiente): archivo existe; abre con Rasterio; driver GeoTIFF;
CRS EPSG:32612; transform idéntico a la fuente; resolución 10 m; dimensiones
10980×10980; alineación exacta con el JP2; dtype float32; nodata NaN; píxeles válidos
todos finitos (sin inf); máscara coherente (inválidos = NaN = 75 537 840, 62.6556 %);
lectura tras cerrar/reabrir OK.

## 7. Validación COG

Evidencia física (tag `IMAGE_STRUCTURE` del COG):

- `LAYOUT=COG`, `COMPRESSION=DEFLATE`, `INTERLEAVE=BAND`, `OVERVIEW_RESAMPLING=CUBIC`.
- Tiled (bloques 512×512), overviews internas [2,4,8,16,32].
- Lectura por ventana correcta e idéntica a la lectura completa.
- Georreferenciado (CRS + transform). Máscara/nodata presente.

**COG real**, no una declaración de metadata.

## 8. Validación nodata / máscara

Análisis del warning "`nan` (string) en metadata vs `NaN` float en COG":

- **Contrato EO-GE V1.0**: `band.nodata` admite `number | string | null`. `"nan"`
  es válido según schema (`eo_ge_normalized_data.schema.json`).
- **COG**: nodata = `NaN` (float32); GDAL lo almacena como el tag `GDAL_NODATA`
  (representación interna `"nan"`); Rasterio devuelve `float('nan')`.
- **Rasterio/GDAL**: esperan `NaN` como nodata de rasters float (estándar).
- **Veredicto**: `"nan"` como string es **correcto y consistente** (JSON no puede
  codificar `NaN`; coincide con la representación interna de GDAL). **No se corrige**.
  La diferencia string/float es solo de serialización, no un error de dato.

Máscara: `DN == 0 → NaN`; ningún píxel válido es NaN; ningún DN=0 es reflectancia
física. PASS.

## 9. Validación contractual

Ambos productos validan contra `EO_GE_NORMALIZED_DATA_CONTRACT V1.0`
(`validate_against_contract` → 0 errores).

- `identity`: id determinista `..._B04_REFL_v1` / `..._B08_REFL_v1`.
- `data_class`: `DERIVED_PRODUCT`.
- `source`: ESA / Sentinel-2 / sentinel-2b / msi / sentinel-2-l2a (sin acoplamiento a CDSE).
- `product`, `acquisition`, `spatial` (CRS/bounds/transform/footprint/tile), `processing`
  (`processing_type=DERIVED`), `data` (raster float32, storage COG + checksum),
  `quality`, `provenance` (incluye `parent_dataset` = JP2 fuente).
- Trazabilidad completa: JP2 → procesamiento → COG → metadata → catálogo → checksum.

## 10. Seguridad

- Sin secretos, tokens, passwords ni credenciales en código, metadata o reportes.
- Sin rutas absolutas hardcoded en el código del proyecto.
- Sin archivos temporales rastreados.
- `.venv-wsl/`, `storage/derived/`, `storage/source_cache/`, `*.sqlite`, `__pycache__/`
  confirmados como ignorados (`git check-ignore`).

## 11. Reproducibilidad

Suite completa ejecutada 3 veces (2 completas + 1 S-A.16), resultados idénticos.
Reejecución del procesamiento real reutiliza productos (misma SHA-256, sin duplicar).

## 12. Tests

```text
RUN 1 (full):     207 tests OK (skipped=1)
RUN 2 (S-A.16):   17 tests OK
RUN 3 (full):     207 tests OK (skipped=1)
```

0 failed, 0 errors. El `skipped=1` es `TestRealIngestExternal` (ingesta externa CDSE,
intencional y documentado).

## 13. Integridad de fuentes

B04_10m.jp2 y B08_10m.jp2: existen, legibles, tamaño y SHA-256 conservados,
**no sobrescritos**.

- B04: `bf94442d24e568e478290970a6037ea77c6af47e673cffb748cca36b17b18687` (PASS)
- B08: `82395f6a56307a505d0e508b64a5ae679046cc879897ac1250ba574f7b29a970` (PASS)

Coinciden con los hashes registrados antes de S-A.16.

## 14. Warnings

| ID | Severidad | Hallazgo |
|---|---|---|
| W1 | MEDIUM | SCL no materializado → la máscara es solo `DN==0` (nadata/edge); no hay máscara de nube/sombra. Limitación conocida y acordada en el alcance de S-A.16. |
| W2 | LOW | `nodata` en metadata como string `"nan"` vs `NaN` float en COG — justificado (JSON no codifica NaN); no requiere corrección. |
| W3 | INFO | `requirements.txt` con `rasterio==1.5.1` es un cambio previo no commiteado (no introducido por S-A.16); se conserva. |
| W4 | INFO | `DN=1000` y `DN=10000` no presentes en la escena real; fórmula verificada por unit test. |

## 15. Riesgos residuales

- Reflectancia > 1 (DN > 11000) permanece en el producto; debe interpretarse
  (nube/nieve/glint) vía SCL cuando se materialice.
- Sin máscara de nubes/sombra a nivel de píxel (SCL pendiente).
- Backend de almacenamiento local (OneDrive); evolución a object storage/Zarr/PostGIS
  es futura.

## 16. Decisión final

```
S-A.16 = APPROVED_WITH_WARNINGS
```

- Critical: 0 · High: 0 · Medium: 1 (W1) · Low: 1 (W2) · Info: 2 (W3, W4).
- Producto científico, COG, contrato, seguridad, regresión e integridad: PASS.
- Warnings no bloqueantes (SCL pendiente y representación nodata documentada).
