# S-A.4 — CONTRACT VALIDATION & ADVERSARIAL AUDIT
## EO-GE NORMALIZED DATA CONTRACT V1.0

---

## 1. Alcance

Auditoría adversarial del contrato V1.0 (creado en S-A.3) y de su JSON Schema,
con el objetivo de determinar si puede congelarse como contrato estable.

## 2. Metodología

- Revisión estructural del schema (required, tipos, enums, `additionalProperties: false`).
- Validación de los 5 casos MVP (ejemplos) contra el schema.
- Ataques negativos (casos inválidos) para confirmar que fallan.
- Auditoría semántica, científica, espacial, temporal, de clase de datos, de
  almacenamiento, de escala, de provenance y de versionado.

## 3. Pruebas realizadas

- 5 ejemplos válidos (Sentinel-2 L2A, Sentinel-1 GRD, Landsat C2 L2, ERA5-Land,
  INEGI vector) → todos pasan el schema.
- 19 ataques inválidos → todos fallan correctamente.
- `python -m unittest tests.test_contract_schema` → **24 passed / 0 failed**.

## 4. Resultados (5 casos MVP)

| Caso | Representación | Verificado |
|---|---|---|
| Sentinel-2 L2A | raster multibanda (uint16 + scale/offset), SCL cloud mask | SÍ |
| Sentinel-1 GRD | raster SAR (VV/VH float32, dB), no confundido con radar meteorológico | SÍ |
| Landsat 8/9 C2 L2 | raster multibanda + QA_PIXEL + escala/offset | SÍ |
| ERA5-Land | multidimensional (time/y/x), `data_class=REANALYSIS`, unidades K | SÍ |
| INEGI/SIAP | vector (GeoParquet), `data_class=CARTOGRAPHY`, CRS | SÍ |

## 5. Matriz MVP

| Capacidad | S2 | S1 | Landsat | ERA5-Land | INEGI/SIAP |
|---|---|---|---|---|---|
| Raster | SÍ | SÍ | SÍ | — | — |
| Vector | — | — | — | — | SÍ |
| Time series | — | — | — | (como multidimensional) | — |
| Multidimensional | — | — | — | SÍ | — |
| CRS | SÍ | SÍ | SÍ | SÍ | SÍ |
| QA | SÍ (SCL) | SÍ (nodata) | SÍ (QA_PIXEL) | — | — |
| Uncertainty | SÍ (opcional) | SÍ | SÍ | SÍ | — |
| Provenance | SÍ | SÍ | SÍ | SÍ | SÍ |
| Scale/offset | SÍ | — | SÍ | — | — |
| Temporal interval | SÍ | SÍ | SÍ | SÍ | SÍ (fecha) |

Sin celdas problemáticas.

## 6. Ataques al schema (19 casos)

Campos required ausentes, tipos incorrectos, enums inválidos, timestamps
inválidos, CRS inválido, raster/vector/time_series/multidimensional incompletos,
dimensiones inconsistentes, identity inválida, contract version inválida,
quality inválida, dtype inválido, bounds con conteo incorrecto, propiedad
inesperada a nivel raíz, mismatch de `data.kind`. Todos rechazados.

## 7. Hallazgos

| ID | Hallazgo | Severidad | Estado |
|---|---|---|---|
| F-01 | `footprint`/`transform` ausentes en `spatial` (S-A.3 los listaba) | MINOR | CORREGIDO (añadidos opcionales) |
| F-02 | `format: date-time` no se valida sin `FormatChecker` | MINOR/INFO | DOCUMENTADO (§21 del contrato) |
| F-03 | `nodata` unifica nodata/fill_value | MINOR | DOCUMENTADO (§20) |
| F-04 | Orden de `bounds` [o,s,e,n] es convención, no regex | INFO | DOCUMENTADO |
| F-05 | `data.kind` no prohíbe cuerpo redundante de otro tipo (inofensivo, despacho por `kind`) | INFO | DOCUMENTADO |

## 8. Correcciones

- Añadidos `footprint` (GeoJSON, opcional) y `transform` (6 coeficientes,
  opcional) a `spatial` en el schema.
- Documentadas las limitaciones y la política de validación de `format` en el
  contrato (secciones 20 y 21).

## 9. Riesgos restantes

- La validación de `format: date-time` depende del `format_checker` del
  consumidor (mitigado: documentado + cubierto por tests con checker propio).
- `footprint`/`transform` opcionales: el consumidor debe derivarlos si están
  ausentes (documentado).

## 10. Veredicto

**APPROVED — FREEZE V1.0**

No existen hallazgos BLOCKING ni MAJOR. El contrato representa correctamente los
5 casos MVP sin perder información científica ni crear ambigüedades. Los
hallazgos son MINOR/INFORMATIONAL, corregidos o documentados. El contrato queda
**FROZEN** como **EO-GE NORMALIZED DATA CONTRACT V1.0**.
