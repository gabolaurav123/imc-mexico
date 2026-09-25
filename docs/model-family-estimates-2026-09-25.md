# Estimaciones orientativas por familia de modelo

Fecha de auditoría: 25 de septiembre de 2026. Alcance: reglas de selección para
el fallback familiar, contrastadas con la biblioteca técnica y comercial del
repositorio. Este documento no acredita una tasación ni la identidad de una
máquina concreta. Los precios aquí descritos proceden de observaciones guardadas
el 22 de septiembre; esta auditoría no volvió a consultar esos anuncios.

## 1. Problema que debe resolver

Una foto permite leer `CAT 320D`, pero el sufijo final puede ser ilegible. Eso
puede impedir la identificación exacta y, a la vez, dejar suficiente información
para orientar sobre una familia documentada. La solución conserva ambas cosas:
la incertidumbre del modelo exacto y la utilidad de un rango familiar.

La ruta exacta conserva prioridad. La ruta familiar no debe convertir un sufijo
ilegible en `L`, ni escribir un año o precio exactos. Tampoco debe hacer que
especificaciones de una variante se presenten como características de la unidad.

## 2. Evidencia y límites de la biblioteca actual

| Registro | Información guardada | Alcance admitido |
| --- | --- | --- |
| Caterpillar 320D | Periodo 2007–2026 de LECTURA; sin especificaciones en ese registro | Orientación de catálogo para ese modelo. El extremo 2026 coincide con el año de consulta y no demuestra fabricación continua. |
| Caterpillar 320D L | Periodo 2006–2014 de LECTURA; sin especificaciones en ese registro | Periodo del modelo, no año exacto de una unidad. `320DL` es una diferencia de espaciado; `320D` es otro miembro. |
| 320D L Phase 2 / 2007 / Tier 3 / NACD | Referencia Cat para US: 110 kW, 21.570 kg, capacidad máxima 1,99 m³ y motor C6.4 ACERT | Exclusivamente la configuración indicada por la fuente. El año literal 2007 no determina un intervalo completo de producción. |

Archivos auditados:

- `knowledge/excavadoras/caterpillar_320d_period_2026-09-23.json`.
- `knowledge/excavadoras/caterpillar_320d_l_2007_nacd.json`.
- `knowledge/market/cat-320d-2026-09.json`.
- `knowledge/market/caterpillar_320d_l_listings_2026-09-22.json`.

La relación entre los modelos cuenta con respaldo primario: el [folleto oficial
Cat AEHQ5885-01 APD](https://s7d2.scene7.com/is/content/Caterpillar/C469497),
consultado en esta auditoría, presenta conjuntamente 320D y 320D L. Su portada
distingue tren estándar y largo; además publica 103 kW, 20.350 kg y 21.550 kg para
las configuraciones descritas. Las diferencias frente al registro NACD justifican
mantener el mercado y la variante de cada referencia; compartir familia no hace
intercambiables sus especificaciones.

### Observaciones de mercado guardadas

| Modelo anunciado | Año anunciado | Horas anunciadas | Precio solicitado USD | Configuración adicional documentada |
| --- | ---: | ---: | ---: | --- |
| 320D | 2011 | 7.949 | 60.000 | Sin dato adicional |
| 320D | 2008 | 12.377 | 70.000 | Sin dato adicional |
| 320D | 2008 | 10.506 | 83.500 | Thumb hidráulico |
| 320DL | 2008 | 14.000 | 75.900 | Sin dato adicional |
| 320DL | 2012 | 9.000 | 66.900 | Sin dato adicional |

Todos esos anuncios están registrados como unidades usadas, mercado US y precios
de oferta. Las claves individuales diferencian unidades; dos anuncios pueden
pertenecer al mismo vendedor. La configuración vacía significa que no se registró
ese detalle, no que se haya confirmado equipamiento estándar.

## 3. Contrato mínimo del fallback familiar

### Admisión e identidad

1. Exigir categoría compatible, marca identificada y un indicio literal de
   modelo procedente de una fotografía pertinente o información del propietario.
   No admitir fotografías ajenas a maquinaria ni contradicciones entre equipos.
2. Usar una relación familiar explícita, versionada y sustentada. Para este caso:
   Caterpillar, excavadoras, miembros `320D` y `320D L`/`320DL`.
3. Rechazar coincidencias por prefijo libre: `320D2`, `320D2 L`, `320E` y el `320`
   actual no entran en ese grupo. Un parecido de nombre no establece familia.
4. Conservar marca, modelo literal, variante y nivel de incertidumbre originales.
   Registrar el alcance familiar aparte, sin promover la identificación a clara.
5. No sobrescribir correcciones humanas, incluidos campos que el propietario
   haya vaciado deliberadamente. El cálculo no autoriza publicar una solicitud.

### Año orientativo

Usar únicamente periodos documentados de los miembros compatibles. No obtener
fechas de fabricación del nombre de un PDF, fecha de consulta, copyright o años
de anuncios comerciales. No reducir un rango por preferir una cifra más precisa.

La unión literal de los dos periodos locales es **2006–2026**. Debe conservar su
alcance de referencia familiar y la limitación del extremo superior del 320D.
No es correcto mostrar 2006–2014 para toda la familia excluyendo silenciosamente
el otro registro, ni considerar 2026 año de fabricación de la foto. Si una regla
de calidad descarta el extremo débil, debe registrar ese descarte y abstenerse de
fabricar un límite sustituto. El año exacto sigue perteneciendo a la declaración
del propietario o a evidencia legible de esa unidad.

### Precio orientativo

- Mantener referencias aprobadas y activas, con marca/categoría/modelos activos.
- Seleccionar la observación más reciente por unidad antes de filtrar
  antigüedad, condición o compatibilidad. Rechazar fechas futuras y referencias
  de más de 30 días, conforme a la política existente.
- Deduplicar también entre miembros de la familia: una corrección de modelo en
  un anuncio no convierte la misma máquina en dos comparables.
- Agrupar por mercado, moneda, clase de uso, precio anunciado o venta efectiva,
  y configuración documentada. No convertir divisas ni mezclar esos grupos.
- Exigir al menos dos unidades distintas en el grupo elegido. Respetar
  incompatibilidades expresas con la máquina; no deducir descuentos por horas,
  suciedad o estado visual.
- Con modelo exacto incierto, emitir una referencia familiar condicionada con
  mínimo y máximo; dejar vacío el precio exacto y la propuesta puntual de precio.
  Conservar el modelo literal de cada anuncio, sin renombrarlos todos a 320D.

Con los registros actuales, el grupo de configuración no especificada reúne
cuatro unidades y permite una referencia familiar **USD 60.000–75.900, mercado
Estados Unidos**. El anuncio de USD 83.500 forma otro grupo por su accesorio
hidráulico y no amplía ese rango. Son ofertas; no prueban ventas efectivas, estado
de funcionamiento, costos de importación ni precio local mexicano.

## 4. Procedencia y presentación

El resultado debe guardar, dentro de material firmado, el alcance familiar,
miembros utilizados, identidad de entrada, registros, fechas y límites del
cálculo. `diagnostics` por sí solo no basta: el manifiesto de valoración actual
firma `identity`, `fields` y `comparables`, pero no firma `diagnostics`.

La ficha muestra **Año aproximado**, **Precio estimado**, moneda y mercado. Los
detalles de procedencia permanecen en administración; no se agregan fuentes ni
órdenes de revisión a la descripción comercial. La condición de uso aparente no
confirma funcionamiento y debe seguir diferenciada de una declaración humana.

Los datos técnicos de variantes, horas y ubicación no se completan utilizando
el fallback familiar. La ubicación del mercado de referencia tampoco se copia
como ubicación física de la máquina.

## 5. Criterios de aceptación para la implementación

| Caso | Resultado esperado |
| --- | --- |
| Sufijo L ilegible, marca CAT clara y foto de excavadora coherente | Puede obtener referencia familiar; identidad exacta permanece incierta. |
| Modelo 320D2 o 320 actual | Excluido del grupo 320D/320D L. |
| Mismo anuncio republicado con otro modelo de la familia | Una sola unidad; prevalece la observación más reciente. |
| Thumb hidráulico documentado | Grupo separado del grupo sin dato adicional. |
| Solo un comparable o referencias caducadas | Sin cifra familiar nueva. La ficha sigue siendo editable. |
| Año y precio exactos corregidos por el propietario | Permanecen intactos y tienen prioridad en la ficha. |
| Foto ajena a maquinaria o contradicción de equipos | No se activa el fallback para completar una ficha de máquina. |
| Manipulación de miembros o alcance en una propuesta | La validación del resultado firmado la rechaza. |

La auditoría comprobó la estructura de archivos y la agrupación local de cinco
anuncios, sin llamadas pagadas, cambios de base de datos ni importaciones. Las
pruebas automatizadas y la conexión del helper al flujo corresponden a su cambio
de implementación; este documento establece los límites y los casos esperados.
