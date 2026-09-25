# Publicación guiada y ficha compartida

## Recorrido implementado

1. La cuenta aporta correo, teléfono internacional y canal preferido. Los datos existentes completos se reutilizan.
2. El anunciante elige un tipo de máquina con búsqueda local en tiempo real. No se exige elegir marca ni modelo.
3. Indica si tiene serie o placa. Puede escribir la serie, fotografiar la placa o continuar con fotos generales.
4. «Generar ficha de maquinaria» guarda la entrada y ejecuta la lectura, comprobación de imágenes, investigación técnica, valoración y composición. No admite una generación sin tipo ni sin serie/fotos.
5. La ficha lista reúne fotos, identificación, rangos de precio/año, campos exactos editables, horas, estado de uso, ubicación y descripción. Un análisis nuevo conserva las correcciones del propietario.
6. Desde esa misma pantalla se agregan y ordenan fotos, se comparte un enlace corto o se envía a revisión. Ambas acciones están arriba y abajo.

## Presentación y datos

- Cuatro fotos principales en carrusel y hasta seis adicionales en la ficha compartida. Las placas y documentos permanecen privados.
- El valor y año exactos del propietario tienen prioridad en la ficha pública; los rangos se conservan para consulta y edición.
- Sólo se muestran datos disponibles. No aparecen casillas vacías, notas para administración ni listados de fuentes en la ficha compartida.
- La descripción automática resume hasta cuatro características esenciales. Las especificaciones completas permanecen estructuradas en la base.
- Una única selección de estado de uso. La apariencia no certifica funcionamiento ni reacondicionamiento.
- La serie y el canal de contacto se incluyen únicamente si el propietario activa sus opciones.
- La descarga oficial de PDF está reservada al personal autorizado. La ficha pública ofrece enlace, WhatsApp, Facebook y el menú de compartir del dispositivo; Instagram puede usar este menú o el enlace copiado.

## Referencia IMC y migración

Se revisaron el catálogo real, una ficha de Caterpillar 320D y el formulario de publicación con la sesión disponible. Sus campos esenciales son tipo, marca, modelo, serie, precio, año, horas, ubicación y características técnicas. La selección extensa de marca/modelo de ese formulario se reserva aquí para correcciones posteriores al análisis.

El catálogo principal continúa en https://www.imcmexico.com.mx/catalogo-de-maquinaria. El enlace «máquinas similares» lleva a ese catálogo. No se modificó su código ni se publicó inventario de prueba allí.

El módulo mantiene separados lectura/investigación, datos estructurados, revisión, enlaces compartidos y entrega al sistema principal. Compartir un borrador útil no equivale a aprobarlo ni a publicarlo en IMC. El esquema de la base maestra y sus credenciales siguen siendo necesarios para activar una integración directa; la preparación de datos no presupone que esa conexión exista.

## Base técnica e investigación

La biblioteca pasa de 85 a 553 referencias y de 316 a 1.659 especificaciones. La ampliación documentada se detalla en [el informe del catálogo](catalogue-construction-expansion-2026-09-25.md). El selector cubre 62 denominaciones de construcción de IMC mediante 44 familias canónicas.

El periodo de producción de un modelo puede orientar el año; no acredita la fecha exacta de una unidad. El precio requiere comparables compatibles y fechados. La plataforma no rellena importes, modelos o fechas inventados cuando no existe evidencia suficiente. En ese caso conserva la información obtenida y permite aportar mejores fotos o identificación. La ubicación no se deduce del país de la marca ni de la IP del anunciante.

## Operación y comprobaciones

La migración 0020 añade las fichas compartidas sin sustituir tablas existentes. Los enlaces son revocables, ligados a la revisión autorizada y excluyen documentos privados. Las contradicciones entre imágenes e identificación bloquean compartir/enviar hasta corregirse; no suspenden automáticamente la cuenta.

Se comprobó en navegador el registro/contacto, buscador, pregunta de serie, bloqueo de generación vacía, carga de fotografía, edición de año/precio, enlace corto y ficha pública. El inicio y la ficha se comprobaron con vista de escritorio y móvil de 390 px. Las pruebas automatizadas cubren guardado concurrente, cambios manuales, permisos, privacidad, investigación, importación del catálogo y compatibilidad con publicaciones anteriores.

Antes de desplegar se guardó una copia privada restaurable de PostgreSQL. Las pruebas locales utilizan SQLite y medios aislados.
