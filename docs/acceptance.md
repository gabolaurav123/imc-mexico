# Aceptación y evidencias · IMC México

Fecha de registro: **15 de septiembre de 2026**. Este documento distingue lo implementado, lo probado en desarrollo y lo todavía pendiente en el servicio público. No declara completada la entrega de producción.

## Resumen comprobado

| Área | Resultado registrado | Alcance de la evidencia |
|---|---|---|
| Repositorio | Implementación en `gabolaurav123/imc-mexico`, rama `main` | El commit finalmente desplegado se debe registrar tras publicar |
| Suite automatizada | Primera etapa: **71 pruebas aprobadas, sin omisiones**. Suite ampliada final: **90 pruebas aprobadas, sin omisiones**, en 9,457 segundos | Ejecución local, SQLite en memoria; ffmpeg/ffprobe disponibles |
| Django | Comprobaciones de sistema sin incidencias | No sustituye comprobación del hosting real |
| Neon | Proyecto independiente; migraciones `0001_initial` y `0002_brand_unit_equipmentmodel` aplicadas | No se reutilizaron bases de datos de Puerto Cancún |
| PostgreSQL real | Comprobación transaccional de workflow con rollback | Borrador sin categoría, instantánea, correcciones, aprobación, difusión, retirada y reasignación; sin envío de correo ni archivos persistidos |
| OpenAI real | Dos respuestas `completed` con `gpt-4.1-mini` | Imagen sintética de prueba; placa de motor y serie parcial, sin inventario publicado |
| PDF | Dos páginas renderizadas e inspeccionadas visualmente con Poppler | Imágenes, título largo, tablas, párrafos y notas internas; sin recortes ni superposiciones en ese documento |
| HEIC | Decodificación y vista JPEG reales dentro de la suite | No depende sólo de una extensión declarada |
| Video | MOV real de dos segundos convertido a MP4 H.264/yuv420p; rechazo por duración probado | No acredita todos los videos de celular ni el límite máximo bajo carga de producción |
| SMTP | Prueba aceptada por Resend con remitente de prueba | No acredita recepción. Restricción al propietario mientras no se verifique dominio |
| HTTP público | **57 comprobaciones aprobadas** en el registro consultado hasta las 23:30:19 UTC | HTTPS, acceso/MFA, JPEG/HEIC/MOV, aislamiento, PDF, revisión y difusión revocada; repetir lo afectado tras el commit final |
| Seenode final | **Verificación parcial; cierre pendiente** | Aún no acredita reinicio/redespliegue, recepción real de correo, restauración ni toda la matriz pública |

Las fuentes técnicas, las reglas de consumo y el caso de prueba de IA se detallan en [processing.md](processing.md). El examen del sitio de referencia y sus límites están en [reference-review.md](reference-review.md).

## Pruebas automatizadas

Comando: `python manage.py test`. Se ejecutó con rutas válidas de ffmpeg/ffprobe para incluir video, sin omitir pruebas. Los tests de OpenAI y correo de esta suite usan respuestas controladas para verificar el código; las llamadas reales se registran por separado.

### Workflow y permisos

- Normalización y unicidad del correo; cambiar correo revoca la verificación anterior.
- Privacidad por defecto de archivos y publicaciones.
- Edición de datos incompletos, campos desconocidos y revisión optimista del borrador.
- Rechazo de asignación de propietario, estado o campos no autorizados desde JSON.
- Bloqueo de acceso/edición por otro propietario y separación de permisos del personal.
- Envío con una foto útil y consentimiento; prevención de solicitudes duplicadas abiertas.
- Versiones históricas inmutables, incluso frente a actualizaciones directas del queryset.
- Aprobación condicionada al permiso del anunciante; creación de otra versión sin publicar automáticamente.
- Correcciones con motivo, nueva presentación y rechazo de resolver una solicitud antigua.
- Autorización pública independiente, exclusión de placas/documentos y revocación por retirada o suspensión.
- Contacto congelado y limitado al texto autorizado; una autorización anterior no se hereda al reasignar.
- Copia de maquinaria como borrador con archivos nuevos privados.
- Reasignación excepcional auditada con revocación de aprobación y difusión.
- Catálogos/seed idempotentes e invitación administrativa sin contraseña universal.
- El personal puede revisar/editar, pero no otorgar el consentimiento de difusión de un propietario distinto.
- Sugerencias de duplicados por serie, marca/modelo o hash de archivos, sin fusionar equipos ni tomar decisiones automáticas.
- Plantillas de notificación con variables limitadas, fallback seguro, recordatorios manuales y exportación CSV de analítica con permiso explícito y protección frente a fórmulas.

### Seguridad web y autenticación

- CSRF en mutaciones autenticadas y una solicitud válida con token.
- Aislamiento de maquinaria, análisis, originales, fichas y PDF entre cuentas.
- Denegación de administración para usuarios normales y de acceso privilegiado para staff sin MFA.
- TOTP real válido, acceso tras verificación y rechazo de reutilizar el mismo código.
- Autenticación administrativa por el formulario central con límite de intentos.
- Rechazo de elevación de roles desde perfil o desde permisos del propio usuario.
- Registro normal con consentimientos y aviso en cola; recuperación con respuesta no reveladora.
- Registro público cerrado por defecto y bloqueado mientras falte la apertura operativa o la validación legal.
- Activación de un uso, nueva contraseña e invalidación de sesiones anteriores.
- Redirecciones de acceso restringidas al sitio y cierre de sesión sólo por POST.
- Exclusión de notas internas del panel del anunciante.
- Ocultación de tokens de activación/recuperación del listado y acceso directo a notificaciones del admin.
- Fichas públicas basadas en versión aprobada, con redacción de datos privados y sin usar el borrador posterior.
- Tokens públicos insuficientes si la ficha está deshabilitada; archivos públicos sujetos a lista autorizada y permiso vigente.
- Exportación editorial sin borrar la confirmación existente de publicación externa.
- Consulta comercial vinculada a maquinaria autorizada; rechazo de UUID privados para visitantes u otros usuarios.
- Redacción de tokens en logs, incluyendo excepciones; cabeceras de no almacenamiento y no referencia en acceso/recuperación.

### Procesamiento

- Tipo real de imagen, HEIC, deduplicación, límites y autorización de cargas.
- Almacenamiento sin URL pública y rechazo de rutas inseguras.
- Consentimiento de IA, pertenencia de imágenes y exclusión de documentos/video.
- Cuotas por usuario, globales y de tokens; reservas y deduplicación de trabajos.
- Imposibilidad de convertir una placa de motor o serie ilegible en identificación de la máquina.
- Request estructurado de Responses y exclusión de contactos privados del contexto.
- Resultado separado del borrador; aplicación sólo de campos explícitos de un análisis guardado.
- Preservación del origen cuando el usuario confirma; una corrección manual no se presenta como fuente del fabricante.
- Invalidación de resultados viejos cuando cambia la revisión o los archivos.
- Reintentos limitados, espera entre intentos, recuperación de trabajos interrumpidos y errores sanitizados.
- Intentos y errores de correo sin eliminar el aviso interno.
- Supresión de destinatarios `.invalid` antes de SMTP, sin marcar falsamente el mensaje como enviado.
- PDF público con versión explícita y exclusión de información privada.
- Conservación en modo diagnóstico por defecto; aplicación explícita sólo a sesiones/contadores/analítica vencidos y enlaces de acceso expirados, sin eliminar medios ni maquinaria.

## Evidencia externa específica

### PostgreSQL

El smoke transaccional utiliza la conexión real de Neon y revierte sus datos al finalizar. Detectó un error que SQLite no reproduce: PostgreSQL no permite `FOR UPDATE` sobre el lado nullable de un `OUTER JOIN`. Se corrigieron `save_draft`, `snapshot` y `set_publication` para bloquear sólo la fila de maquinaria mediante `of=('self',)`.

El recorrido de regresión comprueba equipo sin categoría, guardado, instantánea, validación de publicación sin versión aprobada, solicitud, corrección, nuevo envío, aprobación, habilitación de ficha, retirada y reasignación. No debe confundirse esta prueba con una prueba del proceso desplegado en Seenode.

### OpenAI

Se usó una imagen sintética rotulada como prueba, sin presentarla como maquinaria disponible. Incluía placa de motor, serie parcialmente ilegible e instrucciones impresas que debían tratarse como datos. Se realizaron dos llamadas reales. La segunda, después de ajustar la validación, registró 3196 tokens de entrada y 645 de salida.

Se comprobó que la placa correspondía a un componente, que no se trasladaba una serie de motor a la máquina, que las series parciales quedaban nulas y que no se inventaban año, potencia ni horas. El resultado se guardó separado del borrador y no se publicó. Las cuentas de ensayo se identifican como pruebas y quedaron inactivas. Esta evidencia cubre ese caso, no promete exactitud universal de visión.

### Correo

La aceptación SMTP con el remitente de prueba de Resend demuestra autenticación/envío al proveedor en ese ensayo. Aún hace falta:

1. Verificar un dominio y remitente autorizados para esta aplicación.
2. Configurar ese remitente en Seenode.
3. Confirmar recepción real en el correo de prueba autorizado.
4. Abrir un enlace de activación/recuperación desde la dirección pública y comprobar caducidad/uso único allí.

No se realizaron campañas ni envíos masivos. `Notification.status='sent'` significa aceptado por SMTP, no leído ni recibido.

## Recorrido HTTP real y aceptación pendiente

Se consultó el registro de ensayo del 15 de septiembre de 2026, entre 23:26 y 23:30 UTC: **57 comprobaciones con resultado verdadero**. Se utilizaron tres cuentas de prueba separadas (propietario, otro usuario y revisor), MFA real y tráfico HTTPS. La ficha de ensayo se rotuló PRUEBA y quedó deshabilitada al acabar. No se enviaron anuncios al portal principal.

Los resultados siguientes corresponden al despliegue probado en ese momento; después de publicar el último commit hay que repetir los recorridos afectados y confirmar el hash desplegado:

| Prueba obligatoria | Estado público |
|---|---|
| HTTPS, portada y subpáginas | Aprobado por HTTP; 200 en portada, salud, información, contacto, legales y acceso |
| Registro, entrada, salida y recuperación recibida | Entrada/salida y reapertura aprobadas; registro público cerrado por validación legal; correo recibido pendiente |
| Superadministrador activado y MFA desde la URL pública | MFA del revisor de ensayo aprobado; activación de la cuenta administrativa del titular pendiente |
| Usuario normal sin acceso a funciones ni datos ajenos | Aprobado por HTTP |
| Borrador con datos incompletos y sin placa, cierre de sesión y reapertura | Aprobado por HTTP; datos y fotos conservados |
| Carga de fotos, HEIC y video desde celular | JPEG, HEIC→JPEG y MOV→MP4 aprobados en servidor vía HTTP; celular físico/experiencia visual pendiente |
| Análisis real con y sin placa, resultado guardado y revisión explícita | Encolado real y deduplicación de doble clic aprobados; finalización del recorrido público todavía pendiente en el registro consultado |
| Enviar, pedir cambios, responder, reenviar y aprobar | Aprobado por HTTP |
| Ficha web/PDF con fotos, versión correcta y contacto autorizado | PDF interno y público reales y disponibilidad vendida aprobados; revisión visual pública/contacto integral pendiente |
| Archivo privado denegado y ficha pública desactivable | Aprobado por HTTP; enlace de prueba revocado |
| Reinicio y nuevo despliegue conservan cuentas, datos y medios anteriores | Pendiente |
| Worker permanece activo sin computadora local y recupera trabajo interrumpido | Pendiente |
| Errores de IA/correo/carga mantienen el avance y muestran estado real | Carga falsa rechazada sin perder avance; fallos IA/correo públicos pendientes; cubiertos localmente |
| Interfaz móvil, errores de consola y logs de producción | Pendiente |
| Commit desplegado, servicio, región, recursos y costes registrados | Pendiente |
| Backup y restauración comprobados en entorno independiente | Pendiente |

No se debe registrar maquinaria ficticia como inventario público ni enviar paquetes de prueba al portal principal.

También se obtuvo un ZIP editorial real y se comprobó que marcar como vendida actualiza la ficha. Conservar datos al cerrar sesión no equivale a conservarlos tras reiniciar o redesplegar el servicio; esa prueba continúa separada.

## Cierres de la ampliación y pendientes funcionales

La revisión de alcance inicial detectó varios puntos que se ampliaron después: ahora existen sugerencias de duplicados, comparación visual de versiones, plantillas editables de avisos, recordatorios manuales, enlace preparado de WhatsApp, más métricas de operación, advertencias/placas de IA en revisión, leads vinculados a ficha y texto principal de portada editable. Las pruebas de servicio cubren permisos, notificaciones, exportación y vinculación; las comprobaciones de interfaz están en [ui-validation.md](ui-validation.md). La inspección visual pública sigue pendiente.

Pendientes que deben mantenerse explícitos:

- **Analítica:** hay eventos del proceso autenticado, separación `is_test` y exportación CSV autorizada; no se declara terminado un embudo completo con visitas anónimas, captura de origen/campaña y todas las etapas. No se atribuyen identidades a visitas anónimas.
- **Solicitudes sobre datos personales:** se reciben y se gestionan sus estados. La exportación individual, rectificación y supresión/anonimización de registros protegidos requieren resolución operativa del responsable. El comando de conservación no borra instantáneas, auditoría ni medios para dar por resuelta una solicitud.
- **Medios sin referencia:** `retention --inspect-media` detecta candidatos locales y no los elimina. Revisar copias y cargas concurrentes antes de cualquier intervención manual. El inventario remoto de S3 y su política de conservación requieren configuración propia.
- **Documentos legales:** son borradores. Faltan validación del responsable, datos legales definitivos y confirmación operativa de datos comerciales. `registration_open` y `legal_validated` están cerrados por defecto; el registro no se habilita con una sola de estas marcas. No se afirma cumplimiento automático.
- **Infraestructura:** falta verificar volumen persistente, correos generales con dominio válido, proceso continuo, recursos/costes, respaldo real y recuperación en Seenode. Gunicorn usa 240 segundos; validar también el timeout del proxy para video. Una copia en el mismo volumen no protege ante pérdida de ese volumen.

El sitio principal permanece sin modificaciones. No se ha inspeccionado su administración, base de datos o una API privada; el mecanismo implementado es exportación editorial controlada, no una conexión privada supuestamente disponible.

## Registro final por completar

Al cerrar la puesta en producción, completar aquí sin secretos: URL pública, ruta administrativa, procedimiento de acceso, commit desplegado, servicios y costes, región/plan del proyecto Neon, modelo OpenAI, almacenamiento, remitente verificado, evidencias de persistencia y resultados de cada fila pública. Conservar las limitaciones reales que permanezcan.
