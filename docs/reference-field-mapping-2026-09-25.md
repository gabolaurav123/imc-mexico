# Matriz de campos de referencia — 25 de septiembre de 2026

## Propósito y evidencia

Esta matriz ordena los campos de la imagen **«PUBLICACIÓN DE MAQUINARIA»** y
las instrucciones de los apartados 12–20. Es documentación de producto para
revisión; no añade una función, una regla de IMC ni una integración.

La publicación privada de IMC no pudo observarse con una sesión operativa. Por
ello, «IMC observado» sólo significa que el dato figura en una ficha pública o
en la guía pública, y «pendiente» no se convierte en una validación local.
La [matriz asistida anterior](assisted-field-mapping-2026-09-24.md) contiene el
detalle del contrato local y la evidencia de esa limitación.

## Dos intenciones, dos expedientes

| Intención | Significado | Datos principales | Lo que no se debe inferir |
| --- | --- | --- | --- |
| **Solicitud de compra** | Una persona pide que le localicen o propongan una máquina. No es una unidad en venta. | Tipo, marca/modelo deseados, presupuesto y moneda, rango de año, horas máximas, ubicación o radio, observaciones y si acepta renta. | No tiene precio solicitado, fotos, serie ni disponibilidad de una unidad. Tampoco prueba que vaya a publicar en IMC. |
| **Publicar maquinaria** | El anunciante prepara una ficha de una unidad concreta, inspirada en la imagen. | Tipo, marca, modelo, precio solicitado, año exacto o rango/desconocido durante preparación, horas, ubicación, fotos, características y observaciones operativas. | No confundir precio solicitado con una valoración; ni usar el rango de año como año exacto; ni afirmar que «Publicar» haya creado un anuncio en IMC. |

La imagen y la guía pública de IMC respaldan la segunda intención. No se
observó un formulario de solicitud de compra ni se atribuye una estructura de
campos de IMC a esa intención.

## Matriz de campos

`Requerido` se refiere a la intención indicada y a una ficha completa de
referencia, no al borrador inicial ni al análisis. Los campos con «condicional»
no deben bloquear si no se conocen o si aún no existe contrato IMC confirmado.

| Campo y tipo | Solicitud de compra | Publicar maquinaria | Unidad / validación | Desconocido o rango | Origen y destino | Regla de mapeo |
| --- | --- | --- | --- | --- | --- | --- |
| Tipo de máquina · selector buscable | **Requerido** | **Requerido** | Concepto de catálogo; acepta texto pendiente de correspondencia. | No para una solicitud útil; sí puede corregirse. | Imagen: tipo; `Category` local; IMC: tipo público observado. | Reutilizar una sola selección; resolver tipo→marca→modelo sólo con catálogo autorizado. |
| Marca · texto/selector | Condicional | **Requerido si se conoce** | Texto comercial, sin traducir la marca. | Sí, «pendiente». | Imagen; `data.brand`; IMC: marca pública observada. | No crear una marca ni equiparar aliases sin aprobación. |
| Modelo / variante · texto/selector | Condicional | **Requerido si se conoce** | Conservar guiones, espacios y sufijos significativos. | Sí, «pendiente». | Imagen; `data.model`/`variant`; IMC: modelo público observado. | Un alias sólo recupera la misma denominación exacta; no une variantes. |
| Presupuesto · decimal + ISO `USD`/`MXN` | **Requerido si el solicitante lo aporta** | No aplica; aquí existe precio solicitado. | Importe positivo y moneda explícita; conservar importe y moneda originales. | Sí, presupuesto abierto. | Instrucción de compra; sin equivalente IMC observado. | Nunca convertirlo en precio de una unidad ni valoración. |
| Precio solicitado · decimal + ISO `USD`/`MXN` | No aplica | **Requerido sólo al completar una publicación comercial si el destino lo confirma** | No usar `0.00` de la imagen como valor. | Sí en borrador; la falta no es cero. | Imagen USD; `data.price` + `currency`; precio/moneda públicos observados. | Separar del rango de valoración; no convertir moneda sin tasa, fecha y decisión. |
| Año exacto · entero | Condicional | Condicional durante preparación; puede ser exigido por un destino confirmado. | Año real de la unidad, no del modelo; validación local 1800–2200. | Sí: rango o desconocido. | Imagen; `data.year`; año público observado. | Sólo transferir año exacto confirmado. Si IMC lo exige y sólo hay rango, crear incidencia administrativa. |
| Rango de año · dos enteros ordenados | **Útil** | **Útil** durante preparación | `desde ≤ hasta`; marcado como aproximado. | Sí, es el modo explícito de incertidumbre. | Instrucciones; `estimated_year_from/to`; no se observó soporte IMC. | Nunca sustituir `Año` por extremo, medio o valor elegido. |
| Horas máximas / horas de uso · decimal | **Útil** como máximo | Condicional | Número no negativo y base de lectura/declaración cuando exista. | Sí; no guardar cero por ausencia. | Imagen; `data.hours`; horas públicas observadas cuando existen. | «Máximo» de compra no es la lectura de horómetro de una unidad. |
| Renta aceptada / finalidad · enumeración | Condicional: acepta compra, renta o ambas. | Condicional: sólo si el destino/flujo confirma finalidad. | Valores textuales explícitos; no inferir por precio. | Sí: no indicado. | Guía IMC pública menciona Venta/Renta/Venta y Renta/Sólo Guardar; formulario privado no observado. | No afirmar que exista hoy un campo local o que «Sólo Guardar» haga privada una publicación. |
| País, estado/provincia, ciudad y radio · geografía | **Útil** | **Requerido para una ficha completa si se conoce** | Ubicación de la máquina o zona buscada; país + división + ciudad son separados. | Sí, parcial o desconocida. | Imagen; `location_country/region/city`; ubicación pública observada. | No tomar navegador, IP, fabricante, origen ni domicilio del usuario como ubicación. Adaptar Estado a provincia/departamento sin falsear IMC. |
| Características técnicas · pares campo/valor | Condicional, como filtros deseados | Condicional, cuando estén respaldadas | Conservar literal y unidad del fabricante, placa o autor. | Sí. | Imagen; `data` y referencias técnicas; especificaciones públicas variables. | Especificación de modelo no certifica una unidad; no convertir unidades sin equivalencia comprobada. |
| Observaciones · texto privado/operativo | **Útil** | **Útil** | Texto del solicitante o del autor; no descripción comercial. | Sí. | Instrucciones; `data.notes` local; campo IMC privado no observado. | No publicarlo ni incluirlo en metadatos o descripción automática. |
| Serie y placa · texto / evidencia | No aplica salvo que el comprador la use como referencia privada | Condicional | Conservar ceros y caracteres; lectura literal separada de interpretación. | Sí. | Imagen; `serial`, placa y procedencia local; IMC privado pendiente. | Nunca inventar una serie ni exportarla a público. |
| Fotos · archivos y selección | No requeridas para una solicitud | Condicional para borrador/análisis; **4 principales seleccionadas** para objetivo de plantilla, hasta 6 adicionales. | General/detalle públicos separados de placa/documentos privados. | Sí al crear borrador. | Imagen y guía; `Asset`; límites IMC efectivos pendientes. | No duplicar fotos, no deformar, no contar placa/documento como foto pública y no borrar originales históricos. |

## Requisitos por etapa

| Etapa | Solicitud de compra | Publicar maquinaria | Año / horas / ubicación | Fotos y datos privados |
| --- | --- | --- | --- | --- |
| Iniciar borrador | Tipo y cualquier pista disponible. | Tipo y cualquier pista disponible. | Año, horas y ubicación pueden faltar. | Ninguna foto ni serie obligatoria. |
| Ayuda de IA | Tipo, texto o filtros suficientes para una propuesta acotada. | Fotos, placa, serie, marca/modelo o texto suficiente; nunca una consulta vacía. | Proponer rango sólo con evidencia; no inferir ubicación. | Placa queda privada; resultados son revisables. |
| Guardar en cuenta | Datos aportados hasta ese punto. | Datos aportados hasta ese punto. | Se preserva desconocido y procedencia. | Guardar originales y permisos; no exige cuatro fotos. |
| Compartir/publicar Seenode | No convierte la solicitud en anuncio. | Requiere la versión y autorizaciones que el flujo local confirme. | Precio, año y ubicación sólo si fueron confirmados para la versión. | Seleccionar sólo medios públicos autorizados. |
| Enviar a revisión | Tipo y petición suficientes para asignar seguimiento. | Revisar identidad, contradicciones y versión. | Rango no satisface una exigencia de año exacto. | Notas, placa y documentos siguen privados. |
| Preparar ficha de referencia | No aplica como publicación; preparar una solicitud legible. | Cuatro fotos principales seleccionadas y hasta seis adicionales; campos de la imagen según disponibilidad real. | Año exacto/rango/desconocido explícito; horas opcionales; ubicación declarada. | No duplicar archivos ni usar ejemplos de interfaz. |
| Captura manual en IMC | Pendiente: no se observó esa ruta. | Sólo con sesión, contrato y validaciones reales confirmadas. | Si IMC exige exactitud no disponible, registrar incidencia, no fabricar dato. | Revalidar permisos y límites efectivos de IMC inmediatamente antes. |

## Evidencia y revisión posterior

1. La imagen respalda la disposición de la ficha de publicación, sus cuatro
   fotos principales, precio USD, año, horas, ubicación y observaciones; no
   convierte sus valores de muestra en datos reales.
2. La guía pública de IMC respalda la existencia de finalidades de venta/renta y
   la recomendación de cuatro fotografías, pero no prueba el contrato del
   formulario autenticado ni sus validaciones.
3. La fase de compra, el presupuesto, el máximo de horas y el radio geográfico
   se conservan como conceptos de solicitud porque son útiles y no equivalen a
   una máquina anunciada. Antes de integrarlos con IMC debe observarse o
   documentarse su flujo real.
