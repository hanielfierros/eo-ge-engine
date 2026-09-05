# S-A.13 — TECHNICAL AUDIT REPORT
## EO-GE ENGINE (S-A.0 – S-A.12)

**Fecha:** 2026-09-05
**Auditoría:** independiente, crítica, offline
**Veredicto:** `APPROVED_WITH_WARNINGS`

---

## 1. Executive Summary

La infraestructura EO-GE construida en S-A.0–S-A.12 **existe, es coherente con
la arquitectura aprobada y es técnicamente apta para S-A.14 (GitHub Release)**,
con advertencias documentadas que **no bloquean** el release.

No se encontraron defectos **CRITICAL**. Hay **2 HIGH** residuales aceptados
(identidad de reprocesamiento Sentinel-2 y semántica CRS/bounds). El contrato
V1.0 permanece **FROZEN** e intacto. Radar Engine no fue modificado. No se
descargaron datasets reales. Suite: **155 passed / 0 failed / 0 errors**.

Esta auditoría **no** se apoya solo en los 155 tests: se inspeccionó código,
contrato, fixtures, configuración, `.gitignore`, memoria y se reprodujeron
casos de path safety, foreign keys e identidad.

---

## 2. Audit Scope

- **Incluido:** arquitectura, contrato V1.0, identidad, CRS, tiempo, metadata
  científica, calidad, integridad, transacciones, path safety, secretos,
  dependencias, reproducibilidad, calidad de tests, documentación,
  configuración, archivos generados, escalabilidad, arquitectura científica,
  Sentinel-2.
- **Excluido:** S-A.14, Radar Engine, descargas reales, Internet, nuevas
  capacidades, rediseño del contrato, benchmarks.
- **Método:** REQUISITO → IMPLEMENTACIÓN → EVIDENCIA → RIESGO → VEREDICTO.

Estado persistente al iniciar: `current_phase = S-A.12`,
`S-A.13 = NOT_STARTED`. Artefactos de auditoría **ausentes**. S-A.13 se
ejecutó completa en esta sesión.

---

## 3. Architecture Audit

Cadena real inspeccionada:

```
SOURCE → CONNECTOR → SourceRepresentation → NORMALIZER → VALIDATOR
  → STANDARDIZED OBSERVATION → DATA STORE → CATALOG → GeoData Interface
```

| Capa | No debe | Evidencia | Resultado |
|---|---|---|---|
| Connector | normalizar / validar / escribir Catalog / interpretar | `app/connectors/*` entrega SourceRepresentation; no toca store/catalog | PASS |
| Normalizer | descargar / analizar / modificar contrato / inventar críticos | falla si faltan bandas/dtype/CRS/bounds; poda `None` | PASS (con F-09) |
| Validator | modificar datos / descargar / normalizar | operación pura (test de inmutabilidad) | PASS |
| Data Store | interpretar ciencia / SQL de catálogo / cambiar identity | persiste JSON+archivos; rechaza schema INVALID | PASS |
| Catalog | arrays raster / ser Data Store / modificar archivos | SQLite de índice; adapter deriva Item | PASS |
| GeoData Interface | SQL / raster / validar / normalizar / descargar / interpretar | fachada read-only que delega | PASS |

Separación de responsabilidades **mantenida**. No hay acoplamiento al
Interpretation Engine.

**WARNING:** no existe orquestador de escritura; Catalog y Data Store se
coordinan por el llamador (F-04, F-06).

---

## 4. Contract Audit

`docs/EO_GE_NORMALIZED_DATA_CONTRACT_V1.md` vs
`contracts/eo_ge_normalized_data.schema.json`:

- 12 secciones raíz documentadas; schema `required` omite `temporal` y
  `processing` (ambos documentados como **opcionales**). Consistente.
- Enums `data_class` (10) y `data.kind` (4) coinciden.
- `quality.status`: AVAILABLE / PARTIAL / INVALID coinciden.
- `additionalProperties: false` en objetos raíz.
- Ejemplos MVP en `contracts/examples/` válidos (cubiertos por tests de schema).

El normalizer omite `temporal` y `processing` (permitido). `transformations`
vive en `provenance`. Contrato **no modificado** en esta fase.

**WARNING:** el schema no declara el CRS de `bounds` (F-02). Ya era limitación
documentada en S-A.4 (§20: orden de bounds, no CRS).

---

## 5. Identity / Determinism

Fórmula implementada:

```text
SENTINEL2_{product:type|S2MSI2A}_{YYYYMMDDTHHMMSS}_{tile}_v1
```

Ejemplo verificado:
`SENTINEL2_S2MSI2A_20260828T174859_T12RYP_v1`.

- Misma `SourceRepresentation` → mismo `identity.id`: PASS.
- Strings/fechas compactadas de forma determinista (microsegundos recortados).
- `validate_id` rechaza `/`, `..`, vacío.
- `provenance.processing_time` es wall-clock (documentado en el normalizer);
  el resto del objeto es determinista.

**HIGH (F-01, aceptado):** el baseline de reprocesamiento ESA (`N0512` vs
`N0500`) **no** entra en el ID. Reproducción: dos `source_id` distintos
(N0512/N0500) producen el **mismo** deterministic_id. El contrato §6 dice que
`version` es para reprocesamiento, pero los **ejemplos congelados** usan `_v1`.
Corregirlo cambiaría la identidad canónica (cambio de modelo, no un parche
local). No se rediseña en S-A.13.

Clasificación: **WARNING** (determinista; colisión de reprocesamiento residual).

---

## 6. CRS / Spatial

- Código **no** usa EPSG:32613 como CRS universal.
- `T12RYP → 32612`, `T13RFL → 32613`, `T20JLL → 32720` (hemisferio por banda
  MGRS `>= N`). Reproducido.
- El validador rechaza `epsg=32613` con tile `T12RYP` (`S2_CRS_TILE_MISMATCH`).
- CRS ausente + tile ausente → `NormalizationError` (no se inventa).
- No hay reproyección silenciosa.

**HIGH (F-02, aceptado):** `spatial.bounds` se copia del bbox STAC (WGS84
lon/lat) mientras `spatial.crs` es el CRS nativo UTM. El ejemplo del contrato
usa bounds en UTM; la implementación Sentinel-2 no reproyecta (correcto: no
inventar). El consumidor no debe asumir que `bounds` está en `crs`.

**MEDIUM (F-10):** fixture `tests/fixtures/sentinel2_item.json` tiene
`proj:epsg: 32613` para tile `T12RYP` (incorrecto). El pipeline de
normalización usa la otra fixture (`epsg: null`) y deriva 32612. El test del
conector no aserta EPSG, por eso 155 tests siguen verdes.

---

## 7. Temporal

- Timestamps STAC se conservan (incl. `Z` y fracciones).
- Validator exige ISO-8601 y `start_time ≤ end_time`.
- Acquisition time ≠ processing time (este último es `_utc_iso()`).
- `temporal` raíz opcional no se emite (cobertura P5D no se inventa).

**PASS** con INFO: no hay normalización TZ más allá de `Z` → `+00:00` para parseo.

---

## 8. Scientific Metadata

Conservado cuando está en `item_assets` / collection_metadata:

`dtype`, `scale`, `offset`, `nodata`, `gsd`→resolution, cloud cover, checksum,
license (si viene), provenance, footprint.

Ausencias se podan; no se convierten en afirmaciones (`product.version` ausente).

**WARNING (F-05):** `collection_metadata` se indexa como dict plano de bandas
(item_assets), **no** como Collection STAC. `get_collection()` devuelve la
Collection completa; el llamador debe pasar `item_assets`. Documentado en
D-018 y en `docs/EO_GE_SENTINEL2_NORMALIZER.md`. Mal uso →
`NormalizationError` (dtype ausente), no metadata inventada.

**WARNING (F-09):** el conector hace
`license = props.get("license") or "CC-BY-4.0 (Sentinel)"` — default legal si
STAC no trae license.

**LOW (F-18):** `qa_band`/`cloud_mask` = `SCL`, pero SCL no entra en
`bands` (`_BAND_RE` solo B01–B12/B8A).

`storage.format = "COG"` es declaración canónica (S-A.2), no materialización
(documentado; Data Store no convierte formatos). INFO.

---

## 9. Quality

Separación `dataset_quality` / `pixel_quality` / `uncertainty` existe en el
contrato. El normalizer Sentinel-2 solo llena `dataset_quality.cloud_cover_percent`
y pone `status=AVAILABLE`.

Validator: errores→INVALID, warnings→PARTIAL, schema fail→INVALID inmediato.
Cloud cover fuera de [0,100] es ERROR. Checksum ausente es WARNING.

**WARNING (F-06):** el `ValidationResult` **no** se escribe de vuelta a
`quality.status` ni a `catalog.validation_status`. El adapter copia
`quality.status` del objeto normalizado (siempre AVAILABLE en S-A.7). No hay
pipeline orquestado que persista PARTIAL/INVALID semántico. El Data Store
rechaza solo INVALID **estructural** (schema), alineado con
`docs/EO_GE_DATA_STORE.md`.

**WARNING (F-07):** `Sentinel2Validator.is_applicable` acepta cualquier
`processing_level in (L2A, L2)`, lo que incluiría Landsat C2 L2 si se usara
como dispatcher. Hoy se instancia explícitamente; no hay dispatcher.

Reglas Sentinel-2 **no** están en BaseValidator (aisladas en `_product_checks`).

---

## 10. Integrity

- SHA-256 por archivo; `verify()` comprueba existencia, tamaño, checksum y
  metadata schema-válida.
- Escritura atómica JSON (`*.tmp` + `os.replace`).
- `put_metadata`: staging directory + `os.replace` a `normalized/<id>`.
- Idempotencia: mismo contenido OK; distinto → `StorageConflictError`.
- Corrupción→`verify()=False`→restauración: cubierto por test adversarial.

**WARNING (F-14):** `BaseConnector.verify` y ausencia de checksum en manifest
tratan “sin checksum” como no fallido (`True` / no compara).
**WARNING (F-15):** `put_file` hace `os.replace` del binario **antes** de
actualizar `manifest.json`; un crash deja archivo huérfano (verify no lo ve).

No se observó ventana que deje `metadata.json` parcial.

---

## 11. Transactions

`Catalog.register_item`: BEGIN → Item + Assets → commit; rollback en error.
`remove_item`: borra assets y luego item en transacción.

**WARNING (F-03):** `PRAGMA foreign_keys` = **0** (default SQLite/Python).
Se reprodujo: `register_item` con `collection_id` inexistente **es permitido**.
**WARNING (F-11):** `_same_essential` solo compara
`collection_id/source_id/datetime`; no hay UNIQUE `(item_id, asset_key)`;
`register_asset` puede duplicar assets.

Catalog y Data Store **no** comparten transacción (F-04). Bajo operaciones
normales del llamador cuidadoso no hay contradicción persistente; un fallo a
medias sí puede dejar store sin catalog o viceversa.

---

## 12. Path Safety

Reproducido contra `validate_relative_path` / `validate_id`:

| Ataque | Resultado |
|---|---|
| `../` `../../` `..\..\` | BLOCK |
| `C:/evil` `C:\\evil` `/abs` `//server/share` | BLOCK |
| `foo/../bar` vacío `a/b` | BLOCK |
| `....//` | ALLOW (nombre literal, no `..`) |
| `foo/%2e%2e/bar` | ALLOW (no se decodifica; no hay traversal) |

Confinamiento al storage root: **PASS**. Encoded traversal no se interpreta
como path. LOW (F-20): los tests adversariales no cubren UNC ni encoded.

---

## 13. Secrets

Búsqueda en `app/`, `tests/`, `config/`, `docs/`, `reports/`, fixtures:

- Sin claves reales, PEM, tokens, passwords.
- `CDSE_TOKEN` documentado como variable de entorno.
- `config/settings.example.json` sin credenciales.
- `Authorization: Bearer {token}` solo en runtime si se pasa `token`.
- `SOURCE_TOKEN = "SENTINEL2"` no es secreto.

`.gitignore` cubre `.env`, `*.token`, `credentials.*`, `secrets.*`, `*.key`,
`*.pem`.

**PASS.**

---

## 14. Dependencies

`requirements.txt`:

```
jsonschema>=4.0
requests>=2.28.0
```

Ambas se usan (`normalizers/base.py`, `connectors/sentinel2.py`). Sin
duplicados ni dependencias muertas. **WARNING (F-12):** pines abiertos
(`>=`) → drift posible. No se actualizó nada. Sin Internet.

---

## 15. Reproducibility

La suite se ejecutó en esta sesión:

```text
python -m unittest discover -s tests -p "test*.py"
Ran 155 tests in 1.269s
OK
```

- Schema path relativo a `__file__`.
- Tests usan `tempfile` + fixtures del repo.
- Sin rutas `C:\Users\...` en código/tests.
- Sin variables de entorno obligatorias para tests.
- `requests` en tests solo vía mock (pureza offline).

**WARNING:** desarrollo en Windows; pathlib hace el código portable, no hay CI
aún (S-A.14). `processing_time` puede hacer flaky `assertEqual` de objetos
completos al cruzar un segundo (F-19).

---

## 16. Testing Quality

155 tests cubren contrato, conector, normalizer, validator, store, catalog,
interfaz, pipeline e adversarial.

Brechas reales (no se añadieron tests que congelaran el defecto):

- No cubren colisión de baseline (F-01).
- Fixture del item con EPSG incorrecto no se aserta (F-10).
- Path UNC/encoded no cubiertos (F-20).
- Secret scan no recorre `docs/` ni `reports/` (esta auditoría sí).
- `test_deterministic` compara el objeto entero, no solo identity (F-19).
- Mocks del conector son apropiados (offline). Fixtures son representativas
  pero incompletas (pocas bandas, SCL sin dtype).

No se agregaron tests nuevos: añadir uno que acepte la colisión la congelaría;
añadir uno que la prohíba exige rediseño de identidad.

---

## 17. Documentation

Docs de capas coinciden con métodos reales (Connector, Normalizer, Validator,
Data Store, Catalog, GeoData, Testing, contrato).

Desajustes:

- `EO_GE_VALIDATOR.md` afirma que BaseValidator es reutilizable para vector/
  ERA5, pero `_check_raster` exige `kind=raster` (F-08).
- `processing_version` del normalizer es `"0.7"` y User-Agent `"EO-GE-ENGINE/0.6"`
  mientras la memoria está en 0.13 (F-16).
- `EARTH_OBSERVATION_PROJECT_STATE.json` `components` 04–08 seguían
  `NOT_STARTED` pese a S-A.7–S-A.11 (corregido en memoria al cerrar S-A.13).
- No hay README.md / LICENSE (pertenecen a S-A.14).

No se reescribió documentación para ocultar discrepancias.

---

## 18. Configuration

- `config/settings.example.json`: endpoint, colección, timeouts; token vía env.
- `.gitignore`: secretos, `source_cache/`, `storage/`, `catalog/`, `data/`,
  `*.sqlite`, `*.db`, rasters, caches.
- Separación código / config / secretos: PASS.
- `catalog/eo_ge_catalog.sqlite` no está presente (directorio `catalog/` vacío).
- `storage/` vacío. Sin datasets.

---

## 19. Scalability

Evaluación conceptual (sin benchmark):

| Pieza actual | Evolución | Acoplamiento |
|---|---|---|
| LocalDataStore | object storage / COG real | interfaz `DataStore` sustituible |
| SQLite Catalog | PostgreSQL/PostGIS / STAC API | modelo Collection/Item/Asset portable |
| Contrato V1.0 | estable | FROZEN, proveedor-agnóstico |
| GeoData Interface | misma fachada | no SQL propia |
| Zarr / NetCDF | previstos en S-A.2 | no implementados (OK) |

Puntos de acoplamiento: paths relativos en assets, SHA-256 local, bbox search
en Python. **WARNING** de escala, no de corrección.

---

## 20. Scientific Architecture

`data_class` enum cubre OBSERVATION…FIELD_OBSERVATION. Sentinel-2 L2A se
clasifica `SCIENTIFIC_PRODUCT` (no imagen visual). El contrato impide
serializar arrays en JSON. INTERNAL_DERIVED_DATA no está en V1.0 (INFO).

Una imagen visual no se convierte en observación científica: hace falta
SourceRepresentation + metadata de bandas + contrato.

---

## 21. Sentinel-2

- Aislado: `app/connectors/sentinel2.py`, `app/normalizers/sentinel2.py`,
  `app/validators/sentinel2.py`.
- CDSE STAC, colección `sentinel-2-l2a`, MGRS, L2A, bandas, cloud cover:
  implementado.
- Descarga S3 no soportada (documentado S-A.6); HTTP(S) con retry.
- CRS derivado solo si `proj:epsg` ausente; si STAC miente, el validator
  detecta mismatch (no se “corrige” en el normalizer).
- `is_applicable` demasiado amplio (F-07) es el principal riesgo de fugas
  de reglas S2 a otras misiones.

**WARNING** (no FAIL).

---

## 22. Findings

| ID | Hallazgo | Severidad | Estado |
|---|---|---|---|
| F-01 | `deterministic_id` omite baseline ESA (N0512); colisión de reprocesamiento | HIGH | ACEPTADO (residual; no rediseño) |
| F-02 | `bounds` STAC WGS84 vs `crs` UTM nativo | HIGH | ACEPTADO (residual; no reproyectar) |
| F-03 | SQLite `foreign_keys=0`; item sin collection permitido | MEDIUM | DOCUMENTADO |
| F-04 | Catalog + Data Store sin transacción compartida; `exists()` solo mira store | MEDIUM | DOCUMENTADO |
| F-05 | `collection_metadata` = item_assets, no Collection STAC | MEDIUM | DOCUMENTADO |
| F-06 | `ValidationResult` no persiste en `quality.status` / catalog | MEDIUM | DOCUMENTADO |
| F-07 | `Sentinel2Validator.is_applicable` acepta cualquier L2/L2A | MEDIUM | DOCUMENTADO |
| F-08 | BaseValidator exige raster; doc afirma reutilizable | MEDIUM | DOCUMENTADO |
| F-09 | License por defecto `CC-BY-4.0 (Sentinel)` si STAC no trae | MEDIUM | DOCUMENTADO |
| F-10 | Fixture item `proj:epsg=32613` con tile T12RYP | MEDIUM | DOCUMENTADO |
| F-11 | Idempotencia de catalog débil; assets duplicables | MEDIUM | DOCUMENTADO |
| F-12 | `requirements.txt` con pines `>=` | MEDIUM | DOCUMENTADO |
| F-13 | Memoria `components` 04–08 desactualizada | MEDIUM | CORREGIDO (memoria) |
| F-14 | `verify()` True sin checksum | MEDIUM | DOCUMENTADO |
| F-15 | `put_file`: binario antes de manifest | MEDIUM | DOCUMENTADO |
| F-16 | Versiones internas 0.6/0.7 vs proyecto 0.13 | LOW | DOCUMENTADO |
| F-17 | `cloud_cover_max` de DiscoveryQuery no se envía a STAC | LOW | DOCUMENTADO |
| F-18 | SCL referenciada y no listada en `bands` | LOW | DOCUMENTADO |
| F-19 | Test de determinismo compara objeto entero (flaky al segundo) | LOW | DOCUMENTADO |
| F-20 | Encoded `..` y `....//` no bloqueados (no son traversal) | LOW | DOCUMENTADO |
| F-21 | Tabla `catalog_metadata` no usada | LOW | DOCUMENTADO |
| F-22 | Sin README/LICENSE/`.git` | INFO | S-A.14 |

```text
CRITICAL: 0
HIGH:     2  (aceptados, no blockers)
MEDIUM:   13
LOW:      6
INFO:     1
```

---

## 23. Corrective Actions

- **Código de producción:** ninguna. Los HIGH requieren rediseño de identidad
  o campo `bounds_crs` (contrato FROZEN) / reproyección (prohibida).
- **Memoria:** actualizada (F-13) y veredicto S-A.13 registrado.
- **Tests nuevos:** no. Evita congelar F-01 como comportamiento deseado.
- **Dependencias:** ninguna.

---

## 24. Residual Risks

1. Reprocesamiento Sentinel-2 (Nxxxx distinto) colisiona en el Data Store
   (`StorageConflictError` si el metadata difiere). Mitigación futura: incluir
   baseline en `identity.version` en una revisión de identidad (no V1.0).
2. Consumidores GIS que interpreten `bounds` en el CRS nativo obtendrán
   coordenadas erróneas. Mitigación: tratar bbox STAC como EPSG:4326 hasta que
   el contrato tenga `bounds_crs`.
3. Escritura a medias Catalog/Store. Mitigación: orquestador futuro.
4. Drift de `jsonschema`/`requests` por pines abiertos.
5. Descarga real CDSE sigue condicionada a token (S-A.6); no es defecto de
   esta auditoría.

Ninguno impide publicar el repositorio de infraestructura.

---

## 25. Final Verdict

```text
APPROVED_WITH_WARNINGS
```

Criterio S-A.14:

| Criterio | Estado |
|---|---|
| NO CRITICAL | SÍ |
| NO unresolved HIGH blocker | SÍ (HIGH aceptados y documentados) |
| regression PASS | SÍ (155 / 0 / 0) |
| contract intact | SÍ (FROZEN V1.0) |
| identity deterministic | SÍ (con residual de reprocesamiento) |
| integrity PASS | SÍ |
| security PASS | SÍ |
| documentation coherent | SÍ (con warnings) |
| Radar Engine untouched | SÍ |
| no real datasets downloaded | SÍ |

**S-A.14 puede iniciarse.** Esta auditoría **no** inicia S-A.14.
