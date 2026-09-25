# Biblioteca técnica y tipos de maquinaria de construcción

## Resultado de esta ampliación

La biblioteca empaquetada pasa de **85 a 553 referencias de modelo**, y de **316 a 1.659 especificaciones estructuradas**. La nueva entrega añade **468 referencias del fabricante Volvo y su marca histórica Volvo BM**, correspondientes a 463 denominaciones de modelo; cinco referencias adicionales conservan variantes de configuración distintas. No son anuncios, inventario, unidades a la venta ni una base universal de números de serie.

De las referencias nuevas, **358 contienen especificaciones** y **110 conservan únicamente un periodo de producción expresamente documentado**. En total hay **402 periodos nuevos**, comprendidos entre 1970 y 2024. Una página sin tabla útil puede servir para proponer el rango de años del modelo; no se rellenan sus características con cifras de otro equipo.

| Familia | Referencias nuevas | Especificaciones | Periodos documentados |
| --- | ---: | ---: | ---: |
| Excavadoras de orugas, ruedas y compactas | 125 | 347 | 120 |
| Cargadoras sobre ruedas y compactas | 120 | 431 | 95 |
| Camiones articulados | 52 | 174 | 45 |
| Compactadores | 49 | 132 | 29 |
| Pavimentadoras | 38 | 117 | 33 |
| Minicargadores | 34 | 25 | 34 |
| Motoniveladoras | 34 | 71 | 30 |
| Retroexcavadoras | 16 | 46 | 16 |
| **Total añadido** | **468** | **1.343** | **402** |

Los campos se conservan por separado: motor, potencia, peso, capacidad, profundidad de excavación, ancho de tambor, frecuencia de vibración, caudal hidráulico, velocidad de giro o desplazamiento, ancho de trabajo y emisiones, según lo que realmente documenta cada fuente. No se guardan como un párrafo genérico de características.

## Fuente y método

Se consultó el [archivo oficial de productos anteriores de Volvo Construction Equipment](https://www.volvoce.com/global/en/products-and-services/past-products/) el 25 de septiembre de 2026. El archivo contiene documentación de varias marcas adquiridas; esta entrega limita la importación a las identidades Volvo/Volvo BM que pudieron correlacionarse sin ambigüedad con su tabla o periodo de producción.

La recopilación leyó páginas públicas del fabricante. Una tabla de correspondencias explícita transforma etiquetas de fabricante en campos existentes de la ficha. Cada especificación guarda la etiqueta y el valor originales, su valor con unidad, evidencia, URL, versión de la tabla, fecha de consulta y huella del documento leído. Se conservan rangos y configuraciones, sin inferir un valor exacto de unidad.

Muestras contrastadas directamente:

- [EC210C](https://www.volvoce.com/global/en/products-and-services/past-products/crawler-excavators/volvo-c-series/ec210c/): producción 2007–2013; la referencia conserva ese periodo sin fabricar una tabla de especificaciones.
- [L120E](https://www.volvoce.com/global/en/products-and-services/past-products/wheel-loaders/volvo-c-d-e-f-series/l120e/): periodo 2002–2007 y tabla de configuración de 2006.
- [DD105](https://www.volvoce.com/global/en/products-and-services/past-products/compactors/volvo-asphalt-compactors/dd105/): peso con ROPS, ancho de tambor, potencia y frecuencia; no se mezclan cifras de la variante OSC.
- [BL71](https://www.volvoce.com/global/en/products-and-services/past-products/backhoe-excavator-loaders/volvo/bl71/): periodo 2002–2011 y profundidad con brazo retraído. La profundidad con brazo extendido no sustituye silenciosamente ese valor.
- [A25D 6x6 con motor D9](https://www.volvoce.com/global/en/products-and-services/past-products/articulated-haulers/volvo/a25d-6x6-with-d9-engine/): permanece separado de la configuración con motor D10.

### Controles de calidad

- Se excluyeron tablas con varios modelos que no permiten asignar cada columna o valor a una sola configuración.
- Se excluyeron páginas donde el título y el modelo de la tabla discrepan. Por ejemplo, la página denominada EW160D contiene una tabla titulada EW180D; esa página no se usa para completar ninguna de las dos máquinas.
- Se eliminaron duplicados de navegación y referencias con tablas contradictorias, como las dos entradas del archivo para L250H.
- Los sufijos High-lift, Plus, motores y otras configuraciones explícitas se conservan. No se intercambian versiones sólo porque se parezcan los nombres.
- Una fecha de edición como «2016 specifications» **no** se convierte en año de fabricación ni en periodo de producción. El registro SD115 permite comprobarlo.
- Precios, horas, serie, ubicación, funcionamiento y país de fabricación no se deducen de este catálogo.

El fichero publicado es `knowledge/catalogo_historico_volvo_2026-09-25.json`, declarado por SHA-256 en `knowledge/bundled.json`. `seed` instala únicamente las nuevas referencias aprobadas del paquete y conserva las modificaciones administrativas existentes. Una importación manual sigue entrando pendiente e inactiva.

## Vocabulario del catálogo IMC

Se contrastaron los selectores de [catálogo de maquinaria](https://www.imcmexico.com.mx/catalogo-de-maquinaria) y [solicitud de maquinaria](https://www.imcmexico.com.mx/solicitud-de-maquinaria). Hay 65 denominaciones de opción, además del marcador inicial. **62 denominaciones de construcción se mapean a 44 familias canónicas**, con alias en español e inglés; el paquete define 45 categorías incluyendo «Otra maquinaria», además de las que un administrador ya haya creado.

Se añaden, entre otras, bombas de concreto, fresadoras, plantas de asfalto y concreto, bandas transportadoras, barredoras, mototraíllas, tiendetubos, equipos de lodos, tendido de cables, remolques, petrolizadoras y vibradores de concreto. Los cuatro tipos de compactación siguen vinculados a la familia de compactadores para recuperar su documentación; las excavadoras sobre ruedas y anfibias se encuentran con sus denominaciones IMC sin duplicar la familia de excavadoras.

El buscador utiliza los alias del archivo versionado `portal/data/imc_type_taxonomy.json`; no necesita consultar la web de IMC mientras el usuario escribe. «Avioneta» y «Vehículo marino» quedan fuera del sector de construcción. «Oferta especial» es una etiqueta comercial y no se crea como tipo de máquina. Las tres exclusiones están registradas explícitamente.

## Alcance práctico y pendientes

Esta biblioteca facilita investigar un modelo reconocido y proponer sus datos esenciales y un rango de años documentado. **El rango de producción es del modelo, no una lectura del año exacto de la máquina fotografiada.** Las correcciones del propietario siguen teniendo prioridad.

La ampliación nueva se concentra en Volvo/Volvo BM y complementa las referencias Caterpillar, Toyota, JLG, Wacker Neuson y otras ya existentes. Todavía no cubre todas las marcas ni todos los modelos del mercado. Las familias nuevas del selector no implican automáticamente fichas técnicas completas de cada marca; los modelos sin referencia necesitan investigación externa.

No se incorporan precios inventados a una tabla técnica. La estimación comercial necesita comparables de mercado fechados y compatibles, que utiliza el sistema de valoración separado. Una ficha de fabricante no acredita precio actual, estado de una unidad ni país donde se encuentra.

## Verificación

Las pruebas específicas comprueban correspondencia de tipos IMC, recuperación global del periodo EC210C sin ubicación, separación de motores D9/D10, fechas de folleto que no se convierten en años y ausencia de datos privados o precios en la biblioteca. La prueba integral existente recorre cada referencia aprobada y comprueba que sus campos atraviesan la normalización real de investigación.

Resultado local del grupo `test_knowledge_catalogue.py`, `test_imc_archive_expansion.py` y `test_technical_knowledge_aliases.py`: **30 pruebas y 1.577 subpruebas correctas**. Se utilizó SQLite de pruebas aislado; no se escribió en la base de producción ni se hicieron llamadas pagadas de IA. La comprobación directa de las 468 referencias nuevas devolvió todos sus campos previstos sin rechazos de normalización.
