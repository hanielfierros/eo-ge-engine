# S-A.17 — Release

- Fecha: 2026-09-06
- Motor: EO-GE Engine
- Fase: S-A.17 (NDMI / NDWI / SAVI) — cierre formal y release

---

## 1. Estado

```
S-A.17 = COMPLETED / APPROVED_WITH_WARNINGS / RELEASED
```

- Auditoría final: `APPROVED_WITH_WARNINGS` (ver `reports/S_A17_FINAL_AUDIT.md`).
- Recomendación: `RELEASE`.

## 2. Auditoría

- CRITICAL: 0 · HIGH: 0 · MEDIUM: 2 · LOW: 1 · INFO: 1.
- Reporte: `reports/S_A17_FINAL_AUDIT.md`.

## 3. Productos liberados

| Producto | ID | Archivo | Resolución |
|---|---|---|---|
| B03 reflectance | `SENTINEL2_..._B03_REFL_v1` | `B03_10m.tif` | 10 m |
| B11 reflectance | `SENTINEL2_..._B11_REFL_v1` | `B11_20m.tif` | 20 m |
| NDWI | `SENTINEL2_..._NDWI_v1` | `NDWI_10m.tif` | 10 m |
| NDMI | `SENTINEL2_..._NDMI_v1` | `NDMI_20m.tif` | 20 m (grid nativo B11) |

Los rasters (COG) y el catálogo SQLite no se versionan (excluidos por `.gitignore`).
Lo liberado es el código, los tests, la memoria y la documentación.

## 4. Tests

```text
python -m unittest discover -s tests -p 'test_*.py'
Ran 231 tests — OK (skipped=1)  (0 failed, 0 errors)
```

- `skipped=1` = `TestRealIngestExternal` (intencional).

## 5. Warnings aceptados

- MEDIUM: SCL no materializado (máscara solo DN==0, sin nubes/sombra).
- MEDIUM: 1 píxel >1 en NDWI/NDMI por reflectancia negativa L2A (matemáticamente correcto, sin clipping).
- LOW: `derive_index_product` hardcodea `_10m.tif` (correcto para índices 10 m).
- INFO: pytest ausente; runner canónico = `unittest discover`.

## 6. Release

- Commit message: `Complete S-A.17 spectral indices and release`
- Branch: `main`
- Remote: `origin` (`https://github.com/hanielfierros/eo-ge-engine.git`)
- Fecha: 2026-09-06
- Resultado del push: verificado (HEAD == origin/main).

## 7. Regla de parada

S-A.17 queda CERRADA. S-A.18 NO se inicia. BRAIN_00/01/02 y Radar Engine no modificados.
