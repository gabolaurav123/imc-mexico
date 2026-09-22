# Ampliación curada del catálogo técnico — 22 de septiembre de 2026

Se añadieron quince referencias técnicas de fabricante al paquete revisado. Son
especificaciones de modelo; no acreditan el año, condición, horas, accesorios,
procedencia ni configuración de una unidad anunciada. Tres registros separados
del archivo global de Volvo contienen periodos de producción literales; esos
periodos no identifican el año de fabricación de una unidad. En las demás
referencias, los años que forman parte de títulos o ediciones describen el
documento y no la fecha de fabricación.

| Categoría | Referencias nuevas | Fuente primaria | Cobertura retenida |
| --- | ---: | --- | --- |
| Excavadoras | 3 | [Caterpillar US: 306 CR](https://www.cat.com/en_US/products/new/equipment/excavators/mini-excavators/100084.html?doBuildAndPrice=Y), [307.5](https://www.cat.com/en_US/products/new/equipment/excavators/mini-excavators/15969612.html) y [310](https://www.cat.com/en_US/products/new/equipment/excavators/mini-excavators/302717362099907.html) | Potencia neta, peso y profundidad publicada. Son fichas US; 307.5 y 310 requieren variante literal Tier 4 / Stage V. |
| Compactadores | 3 | [Wacker Neuson US, tabla de placas reversibles BPU](https://www.wackerneuson.com/us/products/vibratory-plates/reversible-vibratory-plates/0-300-kg/technical-data/tab) | BPU 2540A US, BPU 3050A US y BPU3750Ats: peso operativo, fuerza centrífuga y ancho de placa de cada columna literal. |
| Montacargas | 6 | [Toyota Material Handling, Core IC Cushion 2024](https://www.toyotaforklift.com/content/dam/tmh/marketing/en/pdf/product-spec-brochures/2024_Core%20IC%20Cushion_Spec%20Sheet_Digital.pdf) | 40-8FGCU20/25/30 gasolina/LP y 50-8FGCU25/30/32 LP: capacidad, altura máxima de horquillas y peso total de la columna del modelo. |
| Excavadoras históricas globales | 3 | [Volvo EC140C](https://www.volvoce.com/global/en/products-and-services/past-products/crawler-excavators/volvo-c-series/ec140c/), [EC170D](https://www.volvoce.com/global/en/products-and-services/past-products/crawler-excavators/volvo-d-series/ec170d/) y [EC700C](https://www.volvoce.com/global/en/products-and-services/past-products/crawler-excavators/volvo-c-series/ec700c/) | Archivo global de Volvo: periodos EC140C 2008–2017, EC170D 2015–2021 y EC700C 2007–2016; peso, potencia bruta, capacidad de cucharón y profundidad de excavación publicados. |

Las fichas de Toyota y Wacker Neuson agrupan varios modelos en una tabla. Cada
registro conserva el identificador de modelo y sólo los valores de su propia
columna. Los montacargas se limitan al mercado documental US; no se aplican a
un equipo de México o de otro país si ese mercado no se confirma.

La tabla de Toyota escribe `LP` y `Gasoline/LP` como tipos de potencia. Esos
literales no pasan la validación semántica de un campo `fuel`, que acepta
combustibles completos como `LPG` o `Gasolina / LPG`; no se transformaron ni
se publicaron como si fueran valores literales distintos. La fuente y el tipo
de potencia original permanecen en la versión y nota de cada referencia.

Los pesos de las excavadoras corresponden a las configuraciones explícitas en
las páginas de Cat. En particular, Cat publica los máximos con cabina y equipo
de rodaje o contrapeso concretos. La profundidad 307.5 corresponde al brazo
largo y la del 310 al resumen de configuración publicado. Esas especificaciones no deben convertirse en hechos de una
unidad sin confirmación independiente.

## Archivos y validación prevista

- `knowledge/excavadoras/catalogo_tecnico_mini_cat_2026-09-22.json`: 3 referencias.
- `knowledge/compactadores/catalogo_tecnico_wacker_bpu_2026-09-22.json`: 3 referencias.
- `knowledge/montacargas/catalogo_tecnico_toyota_ic_2026-09-22.json`: 6 referencias.
- `knowledge/excavadoras/periodos_produccion_volvo_2026-09-22.json`: 3 modelos globales con periodo, peso, potencia bruta, capacidad y profundidad documentados.
- `knowledge/bundled.json`: lista explícita y SHA-256 de los cuatro archivos.

El paquete queda en 34 referencias técnicas: 19 anteriores y 15 nuevas. La
instalación debe verificarse con `python manage.py test portal.tests.test_knowledge_catalogue`
y, cuando el entorno de despliegue lo ejecute, `python manage.py seed`. Esta
revisión no ejecuta comandos contra la base de datos.

## Comparables de mercado: Toyota 50-8FGCU25

`knowledge/market/toyota_50_8fgcu25_listings_2026-09-22.json` añade dos
anuncios individuales abiertos en [Eliftruck](https://www.eliftruck.com/), no
una página de resultados. Ambos son del mismo modelo exacto, condición usada,
mercado US, moneda USD y precio anunciado; por eso se mantienen separados de
la base técnica y se incluyen en el manifiesto `knowledge/market/bundled.json`.

| Unidad | Año | Horas | Ubicación declarada | Precio anunciado | Configuración declarada | Página individual |
| --- | ---: | ---: | --- | ---: | --- | --- |
| `3462L` | 2022 | 1.179 h | Hayward, California 94545 | USD 32.500 | LP Gas, cushion, mástil tres etapas | [anuncio](https://www.eliftruck.com/details/932594-2251/year-2022-fuel-lp-gas-make-toyota-model-50-8fgcu25/type-cushion-tire-4-wheel-sit-down-%28indoor-warehouse%29-capacity-5000-condition-used) |
| `U11268` | 2021 | 5.806 h | Euclid, Ohio 44117 | USD 18.950 | LP Gas, cushion, mástil tres etapas | [anuncio](https://www.eliftruck.com/details/1024521-2669/year-2021-fuel-lp-gas-make-toyota-model-50-8fgcu25/type-cushion-tire-4-wheel-sit-down-%28indoor-warehouse%29-capacity-5000-condition-used) |

California y Ohio con sus códigos postales acreditan una ubicación en Estados
Unidos; no se interpretan como país de fabricación. Ambas fichas declaran LP
Gas, neumáticos cushion, mástil de tres etapas y capacidad de 5.000 lb. Año,
horas, estado y precio siguen siendo declaraciones del anunciante.
