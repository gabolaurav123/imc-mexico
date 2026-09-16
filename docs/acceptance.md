# Aceptación y evidencias · IMC México

Estado comprobado al **15 de septiembre de 2026**. La aplicación está publicada y tiene recorridos reales verificados. El registro público sigue cerrado y existen pendientes de operación; este documento no declara completada toda la entrega.

## Servicio publicado

| Elemento | Estado comprobado |
|---|---|
| URL | [imc-mexico.seenode.app](https://imc-mexico.seenode.app) |
| Código | [gabolaurav123/imc-mexico](https://github.com/gabolaurav123/imc-mexico), rama `main`; último código funcional verificado `389c1a997012a888885e9b4d1183ed9da64328bb`, activo en Seenode |
| Seenode | Servicio `974953`, nombre `imc-mexico`, una réplica; independiente del servicio Puerto Cancún |
| Recursos contratados | Basic 512 MB: US$4/mes; volumen persistente 5 GB en `/data`: US$2.50/mes; **total actual US$6.50/mes** |
| Opción no activa | Standard 1 GB: US$7/mes + US$2.50 de volumen = US$9.50/mes; pendiente de pago |
| Recarga | Intento de US$10 rechazado; **sin cobro confirmado** |
| PostgreSQL | Neon Free, Frankfurt, PostgreSQL 18, proyecto independiente; migraciones `0001`–`0005` aplicadas |
| Medios | Originales y vistas privados en `/data/media`, comprobados después del redespliegue |
| Acceso | `/iniciar-sesion/`; panel `/panel/`; `/operaciones/` y `/admin/` requieren permisos y MFA |
| Titular | `gabolaurav@gmail.com`, cuenta creada; invitación y recuperación recibidas en Spam de Gmail. El titular aún debe establecer contraseña y configurar TOTP |
| Analítica opcional | Código desplegado, validado localmente y en PostgreSQL; apagada en producción sin eventos ni cookies de analítica. `0005_optional_acquisition_analytics` aplicada |

Los importes describen la configuración contratada y la opción observada en la sesión. No incluyen consumos de OpenAI, correo u otros proveedores. La aplicación no cobra a anunciantes ni contiene pagos, subastas, financiación o comisiones.

## Resumen de evidencia

| Área | Resultado | Alcance |
|---|---|---|
| Suite automatizada | **117 pruebas aprobadas, sin omisiones**, en 9,280 segundos | SQLite en memoria y ffmpeg/ffprobe disponibles; incluye 19 pruebas de privacidad de analítica |
| CI de GitHub | Ejecución `test` del código funcional `389c1a9` completada correctamente | [Registro de GitHub Actions](https://github.com/gabolaurav123/imc-mexico/actions/runs/35037736956/job/104610525676) |
| Django y JavaScript | Comprobaciones Django y `node --check` aprobadas | Validación de sistema/sintaxis; no sustituye recorridos externos |
| PostgreSQL real | Workflow transaccional, 27 páginas Django y cinco comprobaciones de analítica aprobadas | Neon real, datos de esas pruebas revertidos; incluye borrador sin categoría, concurrencia y operaciones JSON de analítica |
| Aplicación real | **106 comprobaciones registradas aprobadas, 88 etiquetas distintas** | Incluye HTTPS, base de datos y repeticiones; no representa 106 casos únicos. Registro saneado en `VERIFICACION-IMC.json` de `outputs` |
| IA real | **Cuatro trabajos completados** con `gpt-4.1-mini` | Dos locales y dos en el worker del hosting; casos con placa de motor y sin placa |
| Imágenes y video | JPEG, HEIC→JPEG y MOV→MP4 reales aprobados en producción | Video de dos segundos reproducido en navegador; no acredita carga alta ni máximo de 120 segundos |
| PDF | Interno y público reales por HTTPS; documento de dos páginas inspeccionado visualmente | Fotos, título largo, tablas, párrafos y notas internas sin recortes en el documento revisado |
| Persistencia | JPEG, HEIC, MOV, ficha y análisis conservados tras redespliegues, incluido `389c1a9` | Lectura real de objetos y datos anteriores al redespliegue |
| Correo | Invitación y recuperación recibidas en **Spam de Gmail**, además de `delivered` en Resend | Verificación directa del listado de Gmail; enlace de invitación válido por GET en producción; el titular no ha activado su acceso |
| Interfaz | Revisión pública de escritorio y móvil; consola sin errores/advertencias en la muestra | Portada, acceso, panel, asistente, ficha y reproducción de video; límites en [ui-validation.md](ui-validation.md) |
| Restauración | **34 tablas y 10 archivos** restaurados y verificados en `imc_restore_test` | Entorno aislado; conteos, hashes y tamaños comprobados |
| Respaldo de producción | Último éxito confirmado el **15 de septiembre, 23:35 UTC (17:35 CST)**, 10 archivos, 699,9 KB, `local_only` | Indicador sin alerta de antigüedad; daemon configurado cada 24 horas. Segunda ejecución al intervalo no observada; copia externa S3 pendiente |
| Cierre de ensayos | Cinco cuentas de prueba desactivadas, sin privilegios ni contraseña utilizable; fichas compartidas de prueba deshabilitadas | Historial conservado; cuenta administrativa real y sus permisos intactos |

El registro saneado de aplicación contiene 106 comprobaciones aprobadas correspondientes a 88 etiquetas distintas. Incluye HTTPS, base de datos y repeticiones de verificación. El informe de entrega y `VERIFICACION-IMC.json`, en `outputs` del workspace, registran el cierre sin contraseñas ni tokens. Las verificaciones de proveedor, Gmail, restauración y navegador complementan el registro; no se suman como pruebas automatizadas del mismo tipo. El SHA de una publicación posterior que sólo actualice documentación se registra por separado del último código funcional probado. Detalles técnicos: [processing.md](processing.md), [operations.md](operations.md) y [ui-validation.md](ui-validation.md).

## Cobertura automatizada

Comandos: `python manage.py test`, `python manage.py check` y `node --check portal/static/portal/app.js`. OpenAI y SMTP se simulan en la suite para verificar fallos y contratos. Sus llamadas reales y entrega se acreditan por separado. ffmpeg/ffprobe estuvieron disponibles en la ejecución confirmada de 117 pruebas, sin omitir conversión de video.

### Flujo y autorizaciones

- Borradores incompletos, valores desconocidos, guardado con revisión optimista y rechazo de campos, roles o estados no autorizados desde JSON.
- Aislamiento entre propietarios y permisos específicos para revisión, publicación, reasignación y exportación de analítica.
- Envío con foto útil y consentimiento; prevención de solicitudes duplicadas abiertas.
- Versiones inmutables, solicitud ligada a su versión y nueva instantánea al aprobar con la selección de imágenes autorizadas.
- Permiso de anunciante, aprobación de ficha y difusión como decisiones separadas; no se publica automáticamente al aprobar.
- Correcciones con motivo, respuesta, reenvío, historial y rechazo de resolver una solicitud antigua.
- Placas/documentos excluidos de difusión y contacto limitado al consentimiento de la versión aprobada.
- Retirada o suspensión revocan difusión; reasignación auditada exige nuevas autorizaciones; copia de maquinaria crea borrador privado.
- Duplicados sugeridos por serie, marca/modelo o hash, sin fusión automática; seed idempotente, plantillas con variables limitadas, recordatorios manuales y CSV protegido frente a fórmulas.

### Seguridad web y autenticación

- CSRF en mutaciones y logout sólo por POST; redirecciones de acceso limitadas al mismo sitio.
- Originales, análisis, maquinaria, PDF y operaciones denegados a cuentas sin autorización.
- TOTP válido y rechazo de reutilización; personal sin MFA bloqueado de funciones privilegiadas.
- Acceso administrativo central con límite de intentos; perfil y administración impiden elevar permisos propios.
- Correo normalizado y único; cambios de correo revocan su verificación; activación de un uso e invalidación de sesiones al cambiar credenciales.
- Recuperación con respuesta no reveladora; tokens ocultos en listados, logs y errores; cabeceras de no almacenamiento/no referencia en páginas de acceso.
- Registro cerrado por defecto: exige `registration_open` y `legal_validated` simultáneamente.
- Ficha pública basada en versión aprobada, sin notas internas ni series; archivos sujetos a lista aprobada y autorización vigente. Conocer un UUID o token no evita comprobar permisos.
- Consultas vinculadas sólo a maquinaria autorizada; exportación editorial no borra confirmaciones existentes de publicación externa.

### Procesamiento y conservación

- HEIC real, contenido falso rechazado, deduplicación, límites, rutas seguras y almacenamiento sin URL pública.
- Consentimiento de IA, selección de imágenes propias y exclusión de documentos, video y contactos privados del contexto.
- Cuotas, reservas, deduplicación de trabajos, reintentos limitados y recuperación de trabajos interrumpidos.
- Placas de componentes separadas de datos de máquina; series ilegibles/parciales desconocidas.
- Resultados separados del borrador; aplicación explícita con procedencia y revisión vigente; resultados viejos invalidados al cambiar datos/archivos.
- Errores sanitizados; fallos de correo conservan el aviso interno; `.invalid` se suprime antes de SMTP sin marcar envío exitoso.
- PDF público con versión explícita y sin información privada.
- Conservación en diagnóstico por defecto; aplicación explícita a sesiones, contadores, analítica vencida y avisos de acceso expirados. No elimina maquinaria, versiones, auditoría ni medios.

### Analítica opcional

- Desactivada por defecto, sin eventos, cookies de analítica ni panel de preferencias mientras esté apagada. Preferencia explícita protegida por CSRF cuando se configura consentimiento; rechazar no impide usar la aplicación.
- Modo agregado sin identificadores ni cookies de sesión analítica. Los eventos no guardan identidad, IP sin procesar, URL completa ni referrer; el código no transforma visitantes en contactos comerciales.
- Sesión analítica limitada a 30 minutos con rotación diaria de hash; revocar limpia identificadores y contexto de trabajos pendientes. Eventos asíncronos idempotentes, separación de datos de prueba/personal y etapas de visita, registro, carga, análisis y envío.
- `retention --apply` limpia hashes de sesión de más de 30 minutos y contexto de análisis expirado; la aplicación sigue siendo manual. Los 19 tests de privacidad y las cinco comprobaciones PostgreSQL pasaron.
- En producción se comprobó la configuración **apagada**: sin eventos ni cookies de analítica, y HTTP 400 al intentar permitirla mientras está deshabilitada. No se capturaron métricas públicas consentidas antes de validar los legales; el circuito de consentimiento activo está probado localmente y en PostgreSQL.

## Recorrido HTTPS real

Se usaron tres cuentas de ensayo separadas (propietario, otro usuario y revisor), tráfico HTTPS y MFA real. La ficha pública de ensayo se marcó PRUEBA y se revocó al acabar. No se envió inventario ficticio al sitio principal.

| Recorrido | Resultado comprobado |
|---|---|
| Portada, salud, información, guía, ejemplo, preguntas, contacto, legales y acceso | HTTP 200 |
| Inicio/cierre de sesión y reapertura | Aprobado; borrador y fotos conservados |
| Segundo factor administrativo | TOTP real aprobado en la URL pública con revisor de ensayo |
| Protección de cuentas y archivos | Otro propietario y visitante bloqueados; usuario normal bloqueado de operaciones |
| Borrador incompleto y sin placa | Creado y guardado; valores desconocidos conservados |
| Archivos | JPEG guardado, HEIC convertido y vista JPEG accesible, MOV convertido a MP4; archivo falso rechazado sin pérdida |
| IA con placa de componente | Worker del hosting completó el trabajo; doble clic lo reutilizó; serie/año/horas de máquina no inventados |
| IA sin placa | Trabajo real completado; serie/año/horas conservaron valores desconocidos |
| Aceptación de IA | Descripción aplicada por selección del usuario y consumo guardado |
| Revisión editorial | Enviar, pedir cambios, responder, corregir, reenviar y aprobar con historial conservado |
| Fichas y exportación | PDF interno con foto, PDF público de versión aprobada y ZIP editorial reales |
| Difusión | Ficha de prueba autorizada, disponibilidad vendida reflejada y enlace revocado |
| Persistencia | Datos, JPEG/HEIC/MOV y análisis disponibles después del redespliegue verificado |
| Recuperación e invitación | Solicitud HTTPS aprobada; enlace de invitación válido en producción |
| Cierre sobre `389c1a9` | Portada, salud, registro, privacidad y términos HTTP 200; POST de registro no crea cuenta; MFA y operaciones HTTP 200 |
| Analítica apagada | Sin cookies ni eventos; petición de permitir analítica rechazada con HTTP 400 |
| Fin de ensayos | Fichas compartidas de prueba deshabilitadas; cinco cuentas de ensayo desactivadas, sin staff/superusuario ni contraseña utilizable; historial preservado |

Las cuentas y objetos de ensayo se distinguen de datos comerciales. Este recorrido no acredita tolerancia a carga alta, funcionamiento indefinido ni una prueba física desde todos los modelos de celular.

## Evidencia externa específica

### PostgreSQL y persistencia

Las pruebas transaccionales en Neon comprobaron borrador sin categoría, guardado, instantáneas, corrección, aprobación, difusión, retirada y reasignación. Las operaciones que bloquean filas usan `select_for_update(of=('self',))` para no bloquear el lado nullable de un `OUTER JOIN` en PostgreSQL. Estas pruebas revierten sus datos al terminar.

La persistencia del servicio se comprobó separadamente: JPEG, HEIC, MOV y resultados de IA anteriores siguieron disponibles después de los redespliegues, incluido `389c1a9`. Neon tiene aplicadas `0001`–`0005` y el código correspondiente está desplegado. Las cinco comprobaciones de analítica en PostgreSQL pasaron con rollback: datos anónimos sin identidad, finalización asíncrona idempotente, revocación de hash/contexto, rechazo en modo agregado y expiración del contexto JSON.

### OpenAI y consumo

Se completaron dos trabajos locales y dos en Seenode con `gpt-4.1-mini`, usando materiales sintéticos rotulados como prueba. El caso de placa de motor incluía serie parcialmente ilegible y texto que debía tratarse como datos. Se conservó la separación entre componente y máquina y quedaron desconocidos los campos sin evidencia.

Un trabajo local registró 3196 tokens de entrada y 645 de salida; uno del hosting registró 3197 de entrada y 812 de salida. El resultado quedó guardado y requirió selección explícita para aplicarlo. La prueba verifica esos casos y el circuito, no exactitud universal de visión.

Producción usa una credencial exclusiva; la anterior fue revocada. Sus cuotas son **10 trabajos por usuario/día, 50 globales/día, 100000 tokens/día y dos intentos por trabajo**. Son controles de admisión, no una garantía monetaria rígida. El worker real se ejecutó en el hosting sin depender de un proceso local. La recuperación tras interrupción está probada en la suite; no se documentó una interrupción forzada del worker de producción.

### Correo y acceso del titular

La credencial SMTP de Resend tiene permiso de envío y fue validada. Resend registró **delivered** para invitación y recuperación de `gabolaurav@gmail.com`. Ambos mensajes también se localizaron directamente en **Spam de Gmail**: invitación a las 19:35 y recuperación a las 19:36, según las horas mostradas en la interfaz. La revisión de Gmail se limitó al listado y metadatos, sin marcar leídos ni activar enlaces. El enlace de invitación se comprobó mediante GET separado en producción. No se publican enlaces privados, contraseñas, tokens ni códigos TOTP.

El titular aún debe establecer su contraseña y configurar la aplicación TOTP en `/panel/seguridad/`. La prueba MFA de una cuenta de ensayo no acredita activación del titular. Los mensajes recibidos se deben buscar también en Spam.

El remitente de prueba actual limita el envío al destinatario propietario permitido. Para otras cuentas falta verificar un dominio/remitente autorizado y probar entrega. `Notification.status='sent'` acredita aceptación SMTP; `delivered` acredita entrega al servidor destinatario. Aquí se comprobó además presencia en el buzón; no se afirma lectura por el titular. No se realizaron campañas ni envíos masivos.

### Interfaz y medios

Se revisó la web pública en escritorio y viewport móvil de 360 × 780: portada, navegación, acceso, panel, pasos del asistente y ficha privada. No se detectó desbordamiento horizontal de página en las vistas móviles medidas. El asistente se revisó también a 1440 × 900. El MP4 derivado del MOV se reprodujo durante la prueba, sin error del elemento de video. La muestra de consola revisada no tenía errores ni advertencias.

La corrección de contenido público y logout se verificaron sobre `535c6c6`; el aviso de registro cerrado se revisó visualmente en navegador sobre `389c1a9`, además de comprobar por HTTP que el POST no crea cuentas. No se repitió la captura móvil del ajuste de espacios en títulos. Las pruebas DOM de autosave, reintentos y conflictos están delimitadas en [ui-validation.md](ui-validation.md).

### Copia y restauración

Se produjo y restauró una copia real de PostgreSQL y medios en `imc_restore_test`, con verificación de **34 tablas y 10 archivos**, incluidos hashes y tamaños. No se restauró encima de la base operativa ni sobre proyectos ajenos. Esta prueba acredita el formato y recuperación aislada realizada.

El daemon está configurado cada 24 horas. El panel `/operaciones/` mostró un último respaldo de producción exitoso del **15 de septiembre a las 23:35 UTC (17:35 CST)**, con 10 archivos, 699,9 KB y estado `local_only`, sin alerta de antigüedad. Todavía no se ha observado una segunda ejecución al intervalo de 24 horas. No existe destino externo S3 configurado/verificado. Una copia junto a los medios no protege ante pérdida del volumen de 5 GB, y la aplicación no cifra la copia local. Falta validar la recuperación integral ante pérdida del servicio/volumen. Procedimientos: [operations.md](operations.md).

## Pendientes de operación y alcance

1. **Activación personal:** el titular establece contraseña y TOTP mediante la invitación recibida.
2. **Legales y apertura:** validar datos del responsable, textos, consentimientos y datos comerciales. Mantener registro cerrado hasta aprobar la apertura; `legal_validated` no acredita por sí sola cumplimiento legal.
3. **Correo general:** verificar dominio/remitente y recepción para destinatarios distintos del propietario permitido por Resend; revisar entregabilidad.
4. **Respaldo:** observar una segunda ejecución a las 24 horas, configurar copia externa privada y probar recuperación integral. El último éxito real ya está confirmado. Revisar capacidad conjunta de medios y copias en 5 GB.
5. **Analítica opcional:** mantenerla apagada hasta validar los legales y autorizar su uso. El código está desplegado y su estado apagado comprobado; una posterior activación deberá comprobar consentimiento, origen/campaña y exportación desde la URL pública.
6. **Capacidad:** no existe prueba de carga del plan Basic. Standard no está pagado ni activo. Verificar videos cercanos al máximo y timeout del proxy antes de prometer ese rendimiento.
7. **Datos personales:** la plataforma recibe solicitudes y gestiona estados; exportar, rectificar o suprimir/anonimizar registros protegidos requiere resolución del responsable. Cambiar el estado no elimina automáticamente todos los datos.
8. **Conservación:** `retention --inspect-media` sólo detecta candidatos locales. La ampliación incluye `audit_media`, de sólo lectura por defecto, con eliminación local explícita de archivos sin referencia de al menos siete días tras revisión operativa. No se ejecutó con `--apply` en producción. El inventario S3 es de sólo lectura y su purga remota no está implementada. No hay purga automática de medios.

El sitio principal [imcmexico.com.mx](https://www.imcmexico.com.mx/) permanece sin cambios. No se accedió a su administración, base de datos o API privada. El mecanismo implementado es exportación editorial controlada; obtener un ZIP no confirma publicación allí. La revisión pública y los recursos propios están descritos en [reference-review.md](reference-review.md).
