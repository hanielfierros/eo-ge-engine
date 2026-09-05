# EO-GE Testing (S-A.12)

## Estrategia de pruebas

Suite offline con fixtures y mocks; sin dependencia de CDSE/Internet. Categorías:
contract, connector, normalizer, validator, data store, catalog, geodata
interface, integración, adversarial, determinismo, idempotencia, integridad,
recuperación y ausencia de secretos.

## Pirámide de testing

- **Unitarias**: contrato (JSON Schema), conector, normalizer, validator, data store, catalog.
- **Integración**: pipeline completo (fixture → … → verify).
- **End-to-end offline**: Normalizer → Validator → Data Store → Catalog → GeoData Interface.
- **Adversariales**: corrupción/recuperación, path traversal, secret scan, offline purity.

## Tests unitarios

Cada capa tiene su suite (`test_contract_schema`, `test_sentinel2_connector`,
`test_sentinel2_normalizer`, `test_sentinel2_validator`, `test_local_data_store`,
`test_catalog`, `test_geodata_interface`).

## Integración

`test_integration_pipeline.py` verifica el flujo completo y su determinismo/idempotencia.

## End-to-end

Pipeline offline completo hasta `search → Item → Asset → Metadata → File → verify`.

## Adversariales

`test_adversarial.py` verifica corrupción/recuperación, path traversal agresivo,
ausencia de secretos en código/fixtures/config y pureza offline (sin `requests.` directo en tests).

## Offline

Ningún test requiere red; los conectores se prueban con mocks de `requests`.

## Integridad

SHA-256/tamaño/existencia vía `verify()`; detecta modificación/eliminación.

## Determinismo

Misma entrada → mismo `deterministic_id`, misma identidad, mismo resultado.

## Idempotencia

Normalizer, Data Store y Catalog son idempotentes (sin duplicados ni corrupción).

## Criterios de aprobación

Suite completa en verde (`0 failures / 0 errors`), repetible, sin secretos ni
datasets reales, y Radar Engine intacto.
