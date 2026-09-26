# Generación de fichas y auditoría — 26 de septiembre de 2026

## Resultado y alcance

Se corrigió la preparación de fichas desde fotos o número de serie para completar el tipo de máquina, marca, modelo, rango estimado de precio, rango estimado de años y un resumen técnico breve. Se conservan Django, las plantillas, la cola existente, los modelos de IA configurados, el orden del asistente, las autorizaciones y las versiones aprobadas. No hay migraciones ni cambios de esquema.

Las horas de uso y la ubicación que escribe la persona se conservan, incluido el valor cero. La previsualización, la ficha compartida y el PDF muestran los rangos aunque también exista un precio de venta o un año exacto. La serie conserva las reglas existentes de privacidad: aparece en la ficha privada y en el enlace preparado cuando su propietario autoriza incluirla.

## Causas encontradas y correcciones

1. **La ruta de número de serie no ejecutaba la estimación de precio.** La etapa de valoración estaba limitada a los trabajos de imágenes. Ahora también se ejecuta después de la investigación por serie, sin exigir fotografías ni que la persona conozca de antemano la categoría.
2. **La investigación podía terminar sin intervalos suficientes.** Se añadió una petición final acotada que completa referencias orientativas del modelo ya identificado. Prioriza los resultados documentados; cuando recurre al conocimiento general del modelo, lo distingue expresamente de una tasación de la unidad y de anuncios observados. No altera las validaciones de las fuentes originales.
3. **Los rangos se ocultaban si existía un valor exacto.** Las vistas terminadas muestran ambos conceptos, con las etiquetas «Rango de precio estimado» y «Rango de año estimado». Sólo se presentan intervalos completos, ordenados y con moneda válida.
4. **La descripción resultaba genérica o demasiado extensa.** Se prepara un resumen técnico de hasta cuatro líneas de texto. Se excluyen series, contactos, afirmaciones de estado mecánico no demostradas y cifras técnicas inventadas. En pantallas estrechas las líneas se ajustan al ancho disponible.
5. **Los textos de estado se filtraban a la ficha terminada.** La presentación elimina campos vacíos y frases de datos pendientes sin convertir esas frases en afirmaciones confirmadas. El borrador conserva la información necesaria para editar y revisar.
6. **Una preparación incompleta podía anunciarse como lista.** Los nuevos trabajos verifican los campos realmente guardados. Si una serie o foto no permite identificar el equipo o completar sus datos, el editor solicita una mejor identificación antes de crear un nuevo enlace compartible. No se inventa información para ocultar una carencia.

Las propuestas nuevas se validan y firman antes de aplicarlas. Los cambios de marca, modelo, condición o contexto técnico invalidan las estimaciones anteriores que la persona no haya confirmado. Las correcciones humanas tienen prioridad, incluso cuando ocurren durante un trabajo de IA. Se ajustaron la reserva de tokens, el tiempo de ejecución y los controles de revocación para la petición adicional; no se aumentaron los límites predeterminados ni se cambiaron los modelos.

## Auditoría transversal

Además del flujo de fichas, se revisaron autenticación, sesiones y MFA; permisos y separación entre cuentas; invitados; enlaces preparados y publicaciones aprobadas; cargas, almacenamiento privado y descargas; cola, presupuestos y reintentos de IA; administración e integración; respaldos, arranque y CI; notificaciones; acceso a fuentes externas, DNS y redirecciones; y puntos de inserción HTML del JavaScript.

Se confirmaron y corrigieron dos defectos adicionales:

- **Bloqueo de integración incompatible con PostgreSQL.** La selección de fotografías intentaba bloquear también el lado opcional de un `LEFT OUTER JOIN`. Ahora limita `SELECT FOR UPDATE` a la fila de maquinaria, manteniendo la operación transaccional existente.
- **Publicaciones accesibles de cuentas desactivadas.** El catálogo, la ficha pública, sus medios y el contacto verifican ahora que el propietario esté activo y no sea una cuenta temporal de invitado. La validación para habilitar publicaciones aplica las mismas reglas.

La revisión cruzada de la implementación nueva detectó y corrigió también incompatibilidades al aplicar clasificaciones visuales, invalidación insuficiente tras corregir datos técnicos y una reserva que excedía por poco el presupuesto predeterminado de tres fotografías. Se añadieron regresiones para estos casos.

## Verificación

Se probaron tanto la persistencia como la salida de previsualización y enlace compartido: identificación investigada desde una serie, ambos rangos, coexistencia con valores exactos, horas cero, país/estado/ciudad, privacidad de la serie, cambios humanos concurrentes, firmas alteradas, datos incompatibles, presupuestos y revocaciones.

La revisión visual incluyó escritorio, ancho móvil de 390 píxeles y PDF. Se comprobó el resumen breve y la ausencia de desbordamiento horizontal. También se comprobó el encabezado de continuación con tablas largas de tres páginas.

La auditoría de dependencias consultó las 51 versiones Python fijadas en PyPI y los 39 paquetes del lockfile en el registro npm. No se encontraron avisos de vulnerabilidad conocidos aplicables en las respuestas consultadas el día de la revisión.

## Límites y operación

- Los intervalos de IA son referencias orientativas del modelo; no certifican el año de fabricación ni el valor comercial de una unidad concreta.
- Un número de serie arbitrario puede no tener referencias públicas suficientes. En ese caso se requiere una foto más clara o datos de identificación adicionales; el sistema no crea una identidad ficticia.
- Las fichas y versiones aprobadas existentes no se reescriben. Para incorporar los nuevos rangos a una ficha anterior, su propietario debe volver a generarla y actualizar su enlace conforme al flujo habitual.
- Las pruebas locales usan SQLite y respuestas simuladas de OpenAI. La regresión de PostgreSQL comprueba el objetivo del bloqueo; no sustituye una ejecución de integración con PostgreSQL real.
- Esta revisión no ejecuta envíos de correo reales, restauraciones de respaldos de producción ni pruebas de carga. La consulta de avisos conocidos y las pruebas aprobadas no constituyen una garantía de ausencia absoluta de errores.
