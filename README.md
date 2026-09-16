# IMC México · Portal de anunciantes

Aplicación complementaria para preparar solicitudes de maquinaria desde fotografías, revisar sugerencias de IA y enviarlas al equipo de IMC México. La cuenta, el permiso de anunciante, la aprobación de una ficha y su publicación son autorizaciones distintas.

Repositorio: [gabolaurav123/imc-mexico](https://github.com/gabolaurav123/imc-mexico), rama `main`. El sitio principal [imcmexico.com.mx](https://www.imcmexico.com.mx/) no se modifica ni se reemplaza. No hay pagos, subastas, financiación, comisiones ni publicación automática en ese sitio.

**Aceptación inicial al 15 de septiembre de 2026:** servicio activo en [imc-mexico.seenode.app](https://imc-mexico.seenode.app), flujo inicial verificado en `389c1a997012a888885e9b4d1183ed9da64328bb`, con **117 pruebas locales aprobadas sin omisiones** y **106 comprobaciones registradas de aplicación aprobadas** (HTTPS, base de datos y repeticiones; 88 etiquetas distintas). Se verificaron MFA, medios, IA real, revisión, PDF, persistencia tras redespliegue, recepción de invitación/recuperación en Gmail y último respaldo local de producción. El registro está habilitado en el código por solicitud del propietario para probar cuentas y borradores; la migración `0006_open_user_registration` abre también las instalaciones existentes al desplegar. La revisión documental, el remitente de correo para otras cuentas y la activación personal del titular siguen pendientes. La analítica está desplegada y apagada, sin eventos ni cookies de analítica. El detalle y los límites están en [Aceptación y evidencias](docs/acceptance.md).

## Identidad y referencias de maquinaria

Se incorpora el logotipo original publicado por IMC México, con naranja `#E38C1A`, azul `#0095D9`, gris metálico y azul oscuro del sitio principal. Está presente en el portal, administración y PDF; el archivo original conserva su contenido y proporción. [Fuentes de identidad](docs/reference-review.md).

El formulario incluye sugerencias editables de nueve marcas y nueve modelos observados en el sitio principal, además de once categorías adicionales (23 categorías iniciales en total). Filtra modelos por marca y tipo, permite escribir otros valores y conserva lo que el usuario haya declarado. No completa automáticamente especificaciones ni importa anuncios como inventario. [Fuentes y alcance del catálogo](docs/machinery-reference.md).

La versión integrada pasó **124 pruebas sin omisiones**, la prueba DOM del catálogo y la revisión visual de un PDF de dos páginas. La identidad y el catálogo no requieren una migración adicional; la apertura del registro usa `0006`.

## Formulario rápido

El recorrido se reduce a **Fotos → Ficha y envío**. La IA completa el borrador automáticamente al pulsar «Preparar mi ficha»; los campos opcionales quedan plegados y la edición sigue disponible. La migración `0007` conserva las fichas existentes. [Comportamiento, protección de cambios y recuperación](docs/quick-intake.md).

La preparación también busca referencias por **serie o modelo**, incorpora especificaciones con sus fuentes y genera la descripción. Ubicación, precio y datos desconocidos no bloquean el envío. Las referencias del modelo se distinguen de los datos de una unidad concreta. [Búsqueda, procedencia y límites](docs/research.md).

La serie puede escribirse de forma opcional junto a las fotos, antes de preparar la ficha. Sin placa ni serie, se investigan la marca y el modelo legibles en fotos generales; si sólo se identifica el tipo, se consultan referencias generales sin atribuir especificaciones a la unidad. La descripción conserva los rasgos visibles, incluso sin identificación exacta.

## Servicio y acceso actuales

| Elemento | Estado comprobado |
|---|---|
| Sitio y acceso | [Portal](https://imc-mexico.seenode.app) · [Iniciar sesión](https://imc-mexico.seenode.app/iniciar-sesion/) |
| Administración | `/operaciones/` y `/admin/`, con rol autorizado y MFA |
| Cuenta del titular | `gabolaurav@gmail.com`; invitación y recuperación recibidas en Spam de Gmail, enlace válido en producción; el titular debe establecer su contraseña y configurar TOTP |
| Seenode | Servicio `974953`, `imc-mexico`; Basic 512 MB, una réplica |
| Almacenamiento | Volumen privado persistente de 5 GB en `/data`; medios en `/data/media` |
| Coste contratado | Servicio US$4/mes + volumen US$2.50/mes = **US$6.50/mes**, sin incluir consumos de proveedores externos |
| Base de datos | Neon Free independiente, Frankfurt, PostgreSQL 18; migraciones `0001`–`0005` aplicadas |
| IA | OpenAI `gpt-4.1-mini`; clave exclusiva de producción y credencial anterior revocada |
| Correo | Resend SMTP con credencial de envío validada; recepción en Gmail confirmada, dominio/remitente general pendiente |
| Respaldo | Restauración real de PostgreSQL y 10 archivos en `imc_restore_test` aprobada; último respaldo local de producción confirmado: 15 de septiembre, 23:35 UTC, 10 archivos y 699,9 KB. Programado cada 24 horas; segunda ejecución aún no observada. Destino externo pendiente |

El intento de recarga de US$10 fue rechazado y no hay cobro confirmado. La mejora opcional a Standard 1 GB (US$7/mes + US$2.50 de volumen = US$9.50/mes) **no está activa** y requiere pago. El plan actual no acredita capacidad bajo carga ni la conversión de videos al límite máximo permitido.

## Qué contiene

- Registro básico, acceso por contraseña, verificación/recuperación por enlace de un uso, perfil, cierre de otras sesiones y solicitudes sobre datos personales.
- Segundo factor TOTP obligatorio para el equipo administrativo; acceso por roles y permisos.
- Asistente de dos pasos: fotos y ficha/envío. Borradores con autoguardado, carga múltiple y detalles opcionales plegados.
- Imágenes JPG, PNG, WEBP y HEIC/HEIF; un video MOV/MP4 opcional. Originales privados y vistas optimizadas sin metadatos EXIF/GPS.
- OpenAI Responses con salida estructurada y relleno automático del borrador al pulsar «Preparar mi ficha». Conserva las correcciones del usuario y la procedencia de IA; no exige aceptar campos uno a uno ni marca la lectura como confirmación humana. El envío a IMC sigue siendo una acción separada.
- Solicitudes, observaciones, correcciones, nueva presentación, versiones inmutables y autorización independiente de imágenes.
- Ficha web y PDF internos; ficha pública y PDF basados en una versión aprobada y en una lista de archivos autorizados. Placas, documentos y series quedan fuera de difusión.
- Administración de anunciantes, maquinaria, solicitudes, medios, mensajes, contactos comerciales, categorías, marcas, modelos, unidades, contenido, límites de IA y auditoría.
- Sugerencias de posibles duplicados sin fusión automática, comparación de versiones, plantillas de avisos y recordatorios manuales, exportación de analítica con permiso específico y consulta vinculada a una ficha.
- Reasignación excepcional con permiso y motivo: revoca difusión, cancela revisiones abiertas y exige nuevas autorizaciones.
- Exportación editorial en ZIP con JSON, PDF e imágenes autorizadas. Exportar no confirma que el portal principal haya publicado la maquinaria.

Las partes que todavía requieren ampliación o una verificación externa se enumeran expresamente en [Aceptación](docs/acceptance.md); esta lista no equivale a declarar cerrado todo el alcance.

## Arquitectura

| Componente | Implementación |
|---|---|
| Aplicación | Python 3.13 o posterior, Django 5.2 LTS, plantillas de servidor y JavaScript sin framework |
| Base de datos | PostgreSQL en Neon; SQLite solamente para desarrollo y pruebas unitarias locales |
| Servidor web | Gunicorn en Linux, archivos estáticos con WhiteNoise |
| Trabajos | Cola persistente en PostgreSQL y comando `runworker`; no requiere Redis |
| Imágenes y video | Pillow, pillow-heif/libheif y ffmpeg/ffprobe |
| Documentos | ReportLab; pypdf para inspección en pruebas; fuentes DejaVu |
| IA | SDK de OpenAI, Responses, Pydantic, modelo configurable |
| Autenticación | Argon2, sesiones Django, CSRF, límites de intentos y django-otp |
| Medios | `PrivateStorage`: volumen persistente local o bucket S3 compatible privado |
| Correo | SMTP, avisos en cola y reintentos limitados |

Las dependencias Python y sus versiones están fijadas en `requirements.txt`. `portal/services.py` contiene las operaciones transaccionales del negocio; las vistas y la administración llaman a esas operaciones.

### Separación de datos y autorizaciones

`Machine` es el borrador editable. `MachineVersion` conserva una instantánea inmutable. `Submission.version` mantiene lo que se envió; al aprobar, se crea otra versión con la selección de imágenes autorizadas y se asigna a `Machine.approved_version`. `Publication` controla cada destino por separado.

Editar un equipo aprobado genera un borrador sin cambiar el contenido de la ficha ya aprobada. Una nueva aprobación deshabilita la difusión anterior hasta que se autorice de nuevo. Retirar el equipo o suspender al anunciante deshabilita su ficha compartible; venderlo actualiza la disponibilidad mostrada. Conocer un UUID nunca sustituye una comprobación de autorización.

## Instalación local

Requisitos: Python 3.13+, Git y ffmpeg/ffprobe en el `PATH` para probar video. En Linux se requieren fuentes DejaVu. Las ruedas de pillow-heif utilizadas incluyen soporte HEIC; se debe comprobar en cada plataforma con las pruebas incluidas.

```bash
git clone https://github.com/gabolaurav123/imc-mexico.git
cd imc-mexico
python -m venv .venv
```

Activa el entorno:

```bash
# Linux/macOS
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Instala y configura:

```bash
python -m pip install -r requirements.txt
```

Copia `.env.example` a `.env`. Para una prueba local usa `DEBUG=true`, una clave de desarrollo nueva, `PUBLIC_URL=http://localhost:8000` y deja `DATABASE_URL` vacío para SQLite. Para no enviar mensajes reales, configura `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`. Los enlaces impresos por ese backend son privados; no compartas los registros de consola.

```bash
python manage.py migrate
python manage.py seed
python manage.py runserver 127.0.0.1:8000
```

En otra terminal, con el mismo entorno:

```bash
python manage.py runworker
```

`seed` es idempotente: crea configuración, categorías, unidades, grupos iniciales, plantillas de avisos y textos básicos. No crea inventario ni contraseñas de demostración; conserva las modificaciones administrativas existentes. Por defecto la IA está deshabilitada y el registro está abierto. En `/registro/` se puede crear una cuenta, entrar al panel y preparar borradores sin esperar al correo de verificación. La verificación se encola y los permisos de anunciante y publicación se revisan por separado. `legal_validated` conserva el estado real de revisión documental y no bloquea la creación de cuentas ni se marca automáticamente como validado. Puedes pausar nuevos registros desactivando `registration_open` en administración; `seed` y los siguientes despliegues respetan esa decisión. Las marcas y modelos son catálogos editables, sin inventar especificaciones de equipos.

El comando `runserver` es exclusivamente para desarrollo. En producción se utiliza `start.py`.

## Variables de entorno

No subas `.env`, claves, cadenas de conexión, medios privados ni copias de base de datos. Configura valores reales mediante los secretos del servicio. `.env.example` contiene únicamente la estructura.

| Variables | Función |
|---|---|
| `DEBUG` | Debe ser `false` en producción |
| `SECRET_KEY` | Secreto aleatorio exclusivo de esta aplicación |
| `PUBLIC_URL` | URL canónica HTTPS publicada, sin barra final |
| `ALLOWED_HOSTS` | Hosts autorizados, separados por comas, sin esquema |
| `CSRF_TRUSTED_ORIGINS` | Orígenes HTTPS completos autorizados |
| `DATABASE_URL` | Conexión PostgreSQL de la aplicación; en Neon puede usar el endpoint agrupado |
| `DIRECT_URL` | Conexión directa PostgreSQL para el bloqueo de despliegue y las migraciones; si falta, se usa `DATABASE_URL` |
| `PORT` | Puerto del proceso, igual al campo Port de Seenode; por defecto `8000` |
| `WEB_WORKERS`, `WEB_THREADS` | Procesos/hilos de Gunicorn; inicialmente uno de cada uno, ajustables al recurso contratado |
| `MEDIA_ROOT` | Carpeta privada persistente; valor actual en Seenode: `/data/media` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Credencial de servidor y modelo de imagen/salida estructurada |
| `OPENAI_TIMEOUT` | Tiempo máximo de la llamada a OpenAI; inicialmente 90 segundos |
| `AI_JOB_STALE_SECONDS` | Recuperación de trabajos interrumpidos; inicialmente 600 segundos |
| `FFMPEG_BINARY`, `FFPROBE_BINARY` | Nombres en PATH o rutas de los binarios |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT` | Backend y servidor SMTP |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Autenticación SMTP privada |
| `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | Elegir la modalidad compatible con el puerto; no habilitar ambas |
| `DEFAULT_FROM_EMAIL` | Remitente autorizado por el proveedor |
| `EMAIL_REPLY_TO` | Buzón real y opcional para respuestas; vacío omite el encabezado |
| `PRIVATE_S3_BUCKET`, `PRIVATE_S3_ENDPOINT_URL`, `PRIVATE_S3_REGION` | Alternativa opcional al volumen local |
| `PRIVATE_S3_ACCESS_KEY_ID`, `PRIVATE_S3_SECRET_ACCESS_KEY` | Credenciales del bucket privado, si no se usa identidad del entorno |
| `BACKUP_DIR`, `BACKUP_INTERVAL_HOURS`, `BACKUP_RETENTION_DAYS` | Carpeta, frecuencia y conservación de copias privadas; ver guía de operación |
| `BACKUP_S3_*`, `PG_DUMP_BINARY` | Destino externo opcional de respaldos y binario compatible de PostgreSQL; ver guía de operación |

`ADMIN_EMAIL` se admite en la configuración como referencia operativa; **no crea ni eleva cuentas por sí sola**. `invite_admin` siempre requiere indicar expresamente el correo autorizado.

Las cuotas, límites de archivos, datos comerciales, retención propuesta y activación de IA se administran en `PlatformSettings`, no mediante valores que se envíen al navegador.

## Crear el acceso administrativo

Con correo, URL pública y worker configurados:

```bash
python manage.py invite_admin CORREO_AUTORIZADO
```

El comando crea una cuenta administrativa con contraseña inutilizable y encola un enlace privado para establecerla. No imprime el enlace ni una contraseña. Una repetición no duplica el aviso; `--resend` se utiliza únicamente para una cuenta que aún no estableció contraseña. Si el correo ya pertenece a una cuenta normal, el comando se detiene y no la eleva automáticamente.

El destinatario abre el enlace, establece su contraseña y configura la aplicación autenticadora en `/panel/seguridad/`. El acceso a `/admin/`, `/operaciones/` y datos ajenos requiere los permisos correspondientes y MFA verificado. El inicio de sesión de administración pasa por el mismo formulario con límite de intentos.

Grupos iniciales: Revisión IMC, Publicación IMC, Comercial IMC y Contenido IMC. El superadministrador asigna los grupos adecuados y `is_staff`; los permisos de publicación y de revisión no se deducen de tener una cuenta normal. Los permisos del propio usuario no se pueden elevar desde su formulario administrativo.

## Pruebas

La [ejecución de CI de GitHub del código funcional `389c1a9`](https://github.com/gabolaurav123/imc-mexico/actions/runs/35037736956/job/104610525676) terminó correctamente.

```bash
python manage.py test
python manage.py check
```

La suite usa SQLite en memoria para que no altere Neon ni ejecute las llamadas externas de OpenAI/SMTP. Instala ffmpeg/ffprobe para que se ejecute también la prueba real de conversión de video; si no están disponibles, esa prueba se omite y no debe presentarse como aprobada. Las variables de los binarios permiten usar una instalación específica.

La suite de aceptación inicial registró **117 pruebas aprobadas sin omisiones**, incluidas 19 de privacidad de analítica. Cinco comprobaciones transaccionales adicionales de analítica en PostgreSQL también pasaron, con rollback. Además se completaron cuatro trabajos reales de OpenAI (dos locales y dos en el hosting), QA visual de un PDF de dos páginas, pruebas transaccionales de workflow en PostgreSQL y revisión de interfaz pública en escritorio y móvil. El registro de aplicación contiene **106 comprobaciones aprobadas, con 88 etiquetas distintas**, e incluye HTTPS, base de datos y repeticiones tras despliegue. El informe de entrega y `VERIFICACION-IMC.json`, guardados en `outputs` del workspace, documentan el cierre. Las cinco cuentas de ensayo se desactivaron y perdieron privilegios/contraseñas utilizables; se conserva el historial. Los simuladores prueban fallos y contratos; entrega de correo, persistencia y restauración se acreditan por sus pruebas externas separadas en [docs/acceptance.md](docs/acceptance.md).

## Despliegue en Seenode

La aplicación es **independiente** dentro del espacio correspondiente a «Puerto Cancún». No modificar el servicio, dominio, variables ni base de datos de Puerto Cancún. El recorrido de aceptación inicial se verificó sobre `389c1a997012a888885e9b4d1183ed9da64328bb`. Se comprobaron salud HTTP 200, medios y resultados de IA anteriores después de su redespliegue, registro bloqueado por POST y operaciones accesibles con MFA. La migración `0005_optional_acquisition_analytics` está aplicada y su código desplegado. La analítica apagada no crea eventos ni cookies y rechaza activación por preferencia mientras siga deshabilitada. El SHA de una publicación posterior que sólo actualice documentación se registra por separado en el informe de entrega.

Configuración del servicio:

| Campo | Valor / criterio |
|---|---|
| Repositorio y rama | `gabolaurav123/imc-mexico`, `main`, commit revisado |
| Runtime | Linux y Python compatible con `requirements.txt` |
| Directorio | Raíz del repositorio |
| Build | `bash build.sh` |
| Start | `python start.py` |
| Puerto | `8000`, con `PORT=8000`, o el valor explícito que se configure en ambos sitios |
| Réplicas | **Una**, mientras se utilice el volumen local |
| Volumen | Persistente en `/data`; `MEDIA_ROOT=/data/media` |
| Salud | `GET /salud/`: comprueba una consulta PostgreSQL y responde 200/503 |
| HTTPS | `https://imc-mexico.seenode.app`, configurada como `PUBLIC_URL` y origen CSRF |

`build.sh` instala ffmpeg, fuentes y herramientas PostgreSQL, instala dependencias Python, recoge estáticos y ejecuta comprobaciones de producción. La conversión real de HEIC/MOV y la generación de PDF se comprobaron en el servicio publicado.

`start.py` ejecuta una migración serializada y después supervisa Gunicorn escuchando en `0.0.0.0:PORT`, `runworker` y el daemon `backup_private`. Comparten el volumen del mismo contenedor. Si un proceso esencial termina inesperadamente, el supervisor termina el contenedor para que el hosting lo reinicie. No se depende de la computadora del desarrollador. No crear otro worker con una carpeta local aislada: no compartiría esos archivos.

`deploy.py` utiliza `DIRECT_URL`, obtiene un bloqueo asesor de PostgreSQL, ejecuta `migrate --noinput` y `seed`, y libera el bloqueo. Así dos arranques coincidentes no migran a la vez. No borra tablas ni reinicia datos. La conexión debe conservar SSL y las opciones suministradas por Neon. El proyecto Neon independiente tiene aplicadas las migraciones `0001`–`0005`, incluidas plantillas/permisos, cierre inicial del registro y estructura de analítica opcional. El siguiente despliegue aplica `0006_open_user_registration`, que activa una sola vez el registro existente y conserva la configuración de IA, analítica, revisión documental y permisos. No requiere nuevas variables de entorno. Si `ADMIN_EMAIL` está configurado para el correo expresamente autorizado, el despliegue prepara su invitación mediante `invite_admin`; no eleva cuentas normales existentes.

La conversión de video es síncrona y puede usar hasta 180 segundos más la inspección inicial. Gunicorn tiene un timeout de 240 segundos; verificar también el límite del proxy de Seenode. Una prueba de dos segundos no acredita el máximo de 120 segundos bajo carga.

### Publicar una corrección

1. Realizar y revisar el cambio, ejecutar pruebas y `check`; revisar que el diff no contenga secretos ni medios.
2. Crear commit y subirlo a `main` sin reescribir historial.
3. Desplegar expresamente el commit verificado en Seenode; cualquier cambio de variables requiere nuevo despliegue.
4. Confirmar commit, logs, `/salud/`, acceso HTTPS y recorrido afectado desde la URL pública.
5. Probar lectura de un archivo previo tras reinicio/redespliegue. Las pruebas de éxito del build no sustituyen esta comprobación.

### Recuperación

El daemon `backup_private` prepara una copia conjunta de PostgreSQL y medios con manifiesto e integridad. Se completó una restauración real en la base aislada `imc_restore_test`, con verificación de 34 tablas y 10 archivos. El panel `/operaciones/` confirmó el último éxito de producción del 15 de septiembre a las **23:35 UTC (17:35 CST)**: 10 archivos, 699,9 KB, estado `local_only`, sin alerta de antigüedad. La frecuencia está configurada en 24 horas; todavía no se ha observado una segunda ejecución a ese intervalo. Su almacenamiento en el mismo volumen no cubre la pérdida de ese volumen; **el destino externo S3 todavía no está configurado ni verificado**. Los comandos, variables, compatibilidad de `pg_dump` y límites están en [Operación y recuperación](docs/operations.md).

Para revertir código, desplegar el último commit validado **sólo si es compatible con el esquema vigente**. No revertir ni borrar migraciones a ciegas. Una migración destructiva necesita una estrategia de restauración o una corrección hacia adelante; ninguna forma parte del arranque habitual. El supervisor y las leases recuperan trabajos interrumpidos hasta el límite de intentos. La restauración aislada no equivale a una prueba de recuperación integral ante pérdida del servicio o volumen de producción.

## Operación

La IA conserva trabajos, intentos, modelo, prompt y consumo. Los límites **configurados en producción** son 10 trabajos por usuario/día, 50 globales/día, 100000 tokens reservados/consumidos al día y dos intentos por trabajo. Pueden diferir de los valores iniciales del seed y se administran en `PlatformSettings`. No son una garantía de coste monetario; no se modifican recargas automáticas de OpenAI. [Procesamiento](docs/processing.md) explica reservas, errores, reintentos y limitaciones.

Para diagnosticar un lote de trabajo:

```bash
python manage.py runworker --once
```

El estado de correo `sent` significa aceptación SMTP. Por separado, Resend confirmó `delivered` para la invitación y recuperación de `gabolaurav@gmail.com`, y ambos mensajes se localizaron directamente en **Spam de Gmail**. El enlace de invitación respondió correctamente en producción. El titular todavía debe establecer su contraseña y configurar TOTP; debe buscar los mensajes también en Spam. El envío actual usa el remitente de prueba y el destinatario propietario permitido; falta verificar un dominio/remitente apto para destinatarios generales antes de abrir el servicio al público. La presencia de los mensajes en el buzón no acredita lectura o activación por el titular.

Las direcciones del dominio `.invalid` de los ensayos nunca se envían a SMTP; quedan marcadas como envío de prueba suprimido, no como correo enviado. Los logs sanitizan los tokens de activación/recuperación. Los accesos web no registran esas rutas completas en Gunicorn.

### Avisos y conservación

Las plantillas de avisos se editan en administración con texto plano y las variables `$folio`, `$status`, `$reason`, `$title`, `$name` y `$portal_url`. No incluyen enlaces de activación configurables. Un recordatorio requiere acción manual del personal, permiso y texto concreto. WhatsApp abre un mensaje preparado únicamente cuando existe un teléfono comercial válido; no lo envía automáticamente.

```bash
# Sólo diagnóstico; no cambia registros ni archivos.
python manage.py retention --inspect-media

# Aplicación explícita de expiraciones ya definidas.
python manage.py retention --apply
```

`--apply` elimina sesiones vencidas, contadores de intentos de más de 31 días y analítica anterior a `retention_days` (mínimo 30). Redacta el contenido de avisos de acceso cuyo enlace ya venció y marca como fallidos los que seguían pendientes. Nunca elimina maquinaria, versiones, auditoría ni medios. El inventario local de archivos sin referencia sólo informa candidatos; no borra archivos y no atribuye automáticamente un archivo a abandono. No se programó una purga automática.

`python manage.py audit_media` permite auditar referencias, integridad de rutas y archivos sin referencia. Es de sólo lectura por defecto; la limpieza local exige `--apply --older-than 7`, comprobaciones de antigüedad/referencias y revisión operativa. No se ejecutó esa limpieza en producción. Con S3 únicamente se admite inventario, sin eliminación remota. La guía completa está en [operations.md](docs/operations.md).

La analítica opcional está desplegada y **apagada en producción**. Se comprobó que no crea eventos ni cookies de analítica y que una petición para permitirla recibe HTTP 400 mientras esté deshabilitada. El consentimiento y sus revocaciones están probados localmente y en PostgreSQL; no se capturaron métricas públicas consentidas antes de validar los legales. Cuando se autorice habilitarla, las preferencias se ofrecen en el pie de página y rechazarlas no cambia el acceso. La captura evita identidad, IP sin procesar, URL completa y referrer. El modo agregado no usa identificadores de sesión; con consentimiento, la sesión analítica dura 30 minutos. `retention --apply` limpia hashes vencidos y contexto de trabajos expirado, además de los plazos anteriores.

Los avisos legales son borradores pendientes de validación del responsable de IMC México. El indicador `legal_validated` registra esa revisión; no acredita cumplimiento legal por sí mismo. Las solicitudes de exportación/eliminación/corrección quedan en administración para atenderlas de forma controlada.

## Documentación relacionada

- [Aceptación, resultados y pendientes](docs/acceptance.md)
- [Procesamiento, IA, archivos, correo y PDF](docs/processing.md)
- [Revisión pública del sitio de referencia](docs/reference-review.md)
- [Operación, backups y restauración](docs/operations.md)
- [Interfaz y comprobaciones DOM](docs/ui-validation.md)
- [Contrato de implementación](CONTRACT.md)
