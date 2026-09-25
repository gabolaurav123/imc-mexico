# Ampliación técnica de catálogo — 25 de septiembre de 2026

## Alcance

Se añadieron **50 referencias técnicas de fabricante** y **204 especificaciones documentadas**, separadas del inventario y de los precios de IMC.

| Categoría IMC | Referencias nuevas | Cobertura de fabricante |
| --- | ---: | --- |
| Excavadoras | 11 | Caterpillar: hidráulicas de orugas y ruedas |
| Compactadores | 8 | Caterpillar: rodillo combinado y vibratorios utilitarios |
| Minicargadores | 13 | Caterpillar: sobre ruedas y sobre orugas |
| Montacargas | 5 | Toyota: combustión interna, llanta cushion |
| Motoniveladoras | 3 | Caterpillar: Tier 3 y Tier 4 / Stage V |
| Plataformas elevadoras | 10 | JLG: articuladas, telescópicas, eléctricas y oruga compacta |

Los archivos de datos son:

- `knowledge/catalogo_tecnico_ampliado_2026-09-25.json` (5 referencias y 40 especificaciones).
- `knowledge/catalogo_tecnico_cobertura_2026-09-25.json` (45 referencias y 164 especificaciones).

Cada registro conserva URL de fabricante, fecha de consulta, título de origen, alcance por modelo y evidencia literal por especificación. Las familias se obtuvieron de páginas y fichas primarias de [Caterpillar excavadoras](https://www.cat.com/en_US/products/new/equipment/excavators.html), [compactadores utilitarios Caterpillar](https://www.cat.com/en_US/by-industry/paving/utility-compactors.html), [minicargadores Caterpillar](https://www.cat.com/en_US/by-industry/construction-industry-resources/skid-steer-loaders.html), [motoniveladora Cat 16](https://www.cat.com/en_US/products/new/equipment/motor-graders/motor-graders/1000005460.html), [JLG](https://www.jlg.com/) y la [ficha Toyota Core IC Cushion 2024](https://www.toyotaforklift.com/content/dam/tmh/marketing/en/pdf/product-spec-brochures/2024_Core%20IC%20Cushion_Spec%20Sheet_Digital.pdf).

No son capturas de IMC, anuncios, listas de precio ni evidencia de una unidad individual. No se agrega año, horas, número de serie, precio, país de fabricación ni disponibilidad cuando la fuente no lo documenta.

## Reglas de recuperación

- `scope: model` significa que cada valor describe el modelo o configuración de su ficha, nunca identifica ni certifica una máquina anunciada.
- `market: US` limita la recuperación automática a una ubicación de Estados Unidos confirmada por el usuario. La disponibilidad comercial en México se deja sin afirmar.
- Las variantes no se cruzan: E450AJ, 450AJ y 450AJ HC3 permanecen como tres modelos distintos; 323 Tier 4 / Stage V no se aplica a un 323 Tier 3.
- `type_es`, `type_en` y `model_aliases` describen la referencia. La recuperación acepta sólo un alias exacto una vez normalizado (por ejemplo, `450 AJ` para `450AJ`). No admite coincidencias parciales ni vuelve un alias equivalente a una variante: `450AJ` no recupera `450AJ HC3`.
- Los perfiles de categoría incluyen campos fundamentales para excavadoras, compactación, montacargas, minicargadores, motoniveladoras y plataformas; se conservan unidades publicadas por la fuente.

## Importación, revisión y activación segura

`import_technical_knowledge` importa los JSON locales como referencias **pendientes e inactivas**. El paquete de `seed` verifica ambos archivos por SHA-256 y `install_bundled_knowledge()` activa una referencia empaquetada que todavía no existe, incluso en una base ya creada. El despliegue ejecuta `seed`, por lo que incluir estos JSON en `bundled.json` constituye una activación de referencias nuevas al desplegar.

Por esa razón, el manifiesto empaquetado es una lista de publicación revisada, no una zona de cuarentena. Las importaciones manuales continúan siendo la vía segura para incorporar fuentes que aún deban ser verificadas por el equipo.

Para una base ya operativa:

1. Importe cada archivo sin `--deactivate-missing`.
2. Filtre la Base técnica por estado pendiente y revise fuente, modelo, mercado y evidencia de cada campo.
3. Apruebe y active únicamente las referencias comprobadas que correspondan al alcance comercial deseado.
4. Pruebe la recuperación por denominación canónica y por alias exacto, y confirme que mercado y variante incompatibles no devuelven la referencia.
5. Conserve la procedencia y el estado de revisión como traza de la decisión; no use una referencia de modelo para completar datos de una unidad.

### Muestreo de fuente antes de empaquetar

Se volvió a contrastar una muestra de los valores que ya están en los JSON, sin
escribir en una base de datos. La ficha primaria [Toyota Core IC Cushion](https://www.toyotaforklift.com/content/dam/tmh/marketing/en/pdf/product-spec-brochures/2024_Core%20IC%20Cushion_Spec%20Sheet_Digital.pdf) publica para `50-8FGCU15` capacidad de 1,350 kg, elevación máxima de 3,335 mm, peso de 2,670 kg, motor Toyota 4Y-US y potencia neta de 35 kW; esos son los campos conservados en la referencia, junto con su mercado US y la nota de centro de carga. La página primaria [Cat 16 Tier 4 / Stage V](https://www.cat.com/en_US/products/new/equipment/motor-graders/motor-graders/1000005460.html) muestra en su comparación 216 kW, 32,411 kg y hoja de 4.9 m para esa variante; también distingue la 14 (213 kW, 25,968 kg, 4.2 m) y la 16 Tier 3 (217 kW, 30,620 kg, 4.9 m). Por ello las tres filas quedan como modelos/variantes separados y no se les asignan años de unidad ni disponibilidad.

El importador valida que `model_aliases` sea una lista de textos no vacíos y sin duplicados tras normalización. El mecanismo usa `provenance` existente, por lo que no requiere una migración ni cambia el esquema de la base.
