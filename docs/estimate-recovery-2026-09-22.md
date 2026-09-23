# Recuperación de estimaciones

## Problema y cambio

Una lectura fotográfica omitió la letra pequeña final de `320D L`, iniciando la
investigación de `320D`. Se reforzó la instrucción visual para revisar sufijos de
menor tamaño/contraste y no considerar clara una denominación con letras finales
ilegibles. Cambió la versión del prompt para evitar reutilizar lecturas previas.

Además, la respuesta real del catálogo incluía `| Diggers | LECTURA Specs` y el
adaptador sólo aceptaba `| LECTURA Specs`. Ahora reconoce ese formato literal sin
relajar la coincidencia de marca, modelo, variante, URL ni periodo. Los intervalos
siguen siendo referencias del modelo, nunca años exactos de una unidad.

La valoración descartaba importes con símbolo inicial y moneda al final, como
`$60,000 USD`. Ahora acepta este formato explícito; mantiene el rechazo de importes
sin moneda o con monedas contradictorias. Los índices de Construction Equipment
Guide sólo permiten descubrir enlaces observados a anuncios individuales del
mismo sitio. Sus precios agregados no se usan como comparables. Se mantienen
límites de recuperación y presupuesto de IA.

## Datos de referencia

Se agregó un registro de periodo del modelo 320D y tres anuncios individuales
fechados del mismo modelo. La agrupación separa el anuncio con thumb hidráulico:
los otros dos proporcionan USD 60,000–70,000 como precios solicitados en Estados
Unidos. El modelo 320D L conserva sus propias referencias: periodo 2006–2014 y
anuncios USD 66,900–75,900. No se intercambian datos entre estas variantes.

Las referencias locales reducen consultas repetidas; los precios expiran para el
cálculo después de 30 días. Una ficha sin evidencia suficiente puede continuar
sin inventar cifras. Las correcciones manuales siguen protegidas.

## Verificación

- Regresión con título real del catálogo, normalización y aplicación del periodo.
- Dinero explícito, resolución de índices a anuncios, exclusión de precios del índice.
- Corrección de sufijo con aplicación de año y valor, conservación del precio del
  propietario y presencia de las estimaciones en la primera página del PDF.
- 956 pruebas de servidor y 1,305 subpruebas aprobadas; la prueba de conversión de
  vídeo se ejecutó después con FFmpeg en PATH: 19 pruebas del módulo aprobadas.
  Sin migraciones adicionales.

La ficha reportada se corrigió como una edición asistida, con revisión visual y
referencias registradas en auditoría. Se verificó su PDF real de dos páginas y
su formulario guardado. No se modificaron credenciales, proveedor ni presupuesto.
