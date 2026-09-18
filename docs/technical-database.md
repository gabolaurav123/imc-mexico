# Base técnica y consulta de maquinaria

## Entrega del 18 de septiembre de 2026

Se amplió la base PostgreSQL existente: diez referencias verificadas para nueve
modelos de cuatro fabricantes. Hay excavadoras de orugas y ruedas. La cobertura
exacta, las variantes, mercados y configuración están en
[knowledge/excavadoras/README.md](../knowledge/excavadoras/README.md).

La migración `0013_technical_reference_catalogue` vincula cada referencia técnica
con el catálogo relacional de marca/modelo. La relación se valida contra su
categoría, marca y modelo; no se puede conectar una excavadora a otra familia.
El despliegue instala el paquete revisado mediante `seed`. No crea anuncios.

`knowledge/bundled.json` enumera los archivos revisados y su hash. Un archivo
nuevo o alterado no se activa por estar en una carpeta. La instalación respeta
correcciones, importaciones pendientes y desactivaciones administrativas. El
importador manual guarda referencias pendientes vinculadas al mismo catálogo.

## Consulta y análisis

- `/operaciones/base-tecnica/`: búsqueda por marca, modelo, variante, generación
  o categoría; filtros, cobertura y paginación. Sólo personal autorizado.
- El detalle interno muestra especificaciones, evidencia, fecha de consulta,
  mercado y periodo documentado. Desde allí se abre la edición existente.
- El análisis recupera referencias activas y aprobadas de categoría, identidad,
  variante y mercado compatibles. Reconoce alias como CAT/Caterpillar y espacios
  en identificadores, sin igualar modelos de distinta generación.
- Si se desactiva una marca/modelo, su referencia deja de alimentar el análisis.
- El archivo oficial de Volvo aporta el periodo EC210B 2003–2009. Se separó esa
  referencia de las especificaciones de la configuración 2009: conocer el modelo
  permite proponer su periodo sin atribuir a la unidad las cifras de otro año.
- Un año declarado incompatible excluye la referencia. La placa, los datos
  declarados y las correcciones conservan sus protecciones existentes.
- La recuperación de base local no usa tokens ni ejecuta peticiones externas.
  Si faltan peso, potencia, profundidad o año/periodo, la investigación existente
  continúa con esa evidencia como punto de partida, dentro del mismo presupuesto.
  Un fallo externo conserva los datos locales comprobados; una cancelación no
  permite aplicar resultados parciales. La valoración conserva sus reglas.

El año y los precios requieren evidencia. La base técnica no almacena precios
de una sola unidad como valor universal del modelo. Los comparables siguen en
la capa interna de valoración, con su moneda, mercado y umbral existente.

## Sitios revisados y cambios funcionales aplicados

Se consultaron el [inventario de Foundation Drilling](https://www.foundationdrilling.com/listings),
su [ficha Soilmec SR-30](https://www.foundationdrilling.com/listings/9289785-used-2015-soilmec-sr-30)
y la [Grove GHC130 en MachineryTrader](https://www.machinerytrader.com/listing/for-sale/258197815/2015-grove-ghc130-telescopic-boom-crawler-cranes).

Se tomó como referencia la separación entre fotos, identificación, especificaciones
y datos de venta; el filtrado por atributos; y la ordenación del inventario. En IMC:

- Variante visible en el buscador público.
- Recuento de resultados y orden por fecha, horas, año exacto o precio.
- Orden de precio condicionado a una moneda seleccionada; nulos al final.
- Horas antes del año en identificación y PDF.
- Se conserva la consulta de versiones aprobadas y la omisión de vacíos y datos
  internos desde el servidor.

La Grove es una grúa telescópica sobre orugas y la Soilmec una perforadora:
sirvieron para estudiar el funcionamiento de las fichas, no como documentación
técnica de excavadoras. No se copiaron sus anuncios ni imágenes al inventario.

## Integración y comprobaciones

PostgreSQL sigue siendo la base operativa. La conexión con MySQL de la web
principal requiere su esquema y acceso. Esta entrega no declara esa sincronización.

Las pruebas cubren instalación/reinicio sin duplicados, protección de ediciones,
hash del paquete, permisos de consulta, correspondencia catálogo/referencia,
rechazo de variantes/años incompatibles, aceptación de cada campo por el
normalizador de investigación real, periodo histórico sin especificaciones
prestadas, ordenación por moneda y protección de las publicaciones aprobadas.
Las llamadas al proveedor de IA se simulan en las pruebas automatizadas; la
verificación de las fuentes del paquete se realizó sobre páginas de fabricante.

Resultado final local: **906 pruebas y 1242 subpruebas aprobadas**, con FFmpeg
disponible. `npm run test:ui`, comprobación de Django y comprobación de migraciones
aprobadas. No se hicieron llamadas de pago para estas pruebas.
