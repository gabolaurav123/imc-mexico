# Procesamiento, IA y fichas PDF

## Archivos privados

Los originales y vistas optimizadas usan `portal.storage.PrivateStorage`. No existe
una URL pública de almacenamiento ni una ruta MEDIA pública. Cada descarga pasa por
las comprobaciones de usuario, propietario o versión publicada de las vistas Django.
Los nombres de los archivos almacenados son aleatorios; no se utilizan rutas del usuario.

Configuración inicial ajustable desde administración: 20 fotografías, 20 MB por
fotografía, un video de 100 MB y hasta 120 segundos por maquinaria. JPG/JPEG, PNG,
WEBP y HEIC/HEIF se decodifican realmente mediante Pillow y pillow-heif/libheif;
la extensión o el MIME declarado no bastan para aceptar un archivo. Se rechazan
imágenes animadas, fotografías de menos de 32 píxeles por lado y más de 50 megapíxeles.
La vista JPEG elimina EXIF/GPS y conserva hasta 2400 píxeles; las placas conservan
hasta 3200 píxeles y mayor calidad. El original permanece privado e intacto.
No se realizan retoques ni se alteran defectos o accesorios.

MOV/MP4 requieren **ffmpeg y ffprobe** instalados en el servidor (variables
`FFMPEG_BINARY` y `FFPROBE_BINARY`). Se valida contenedor, pista de video, resolución
y duración; se convierte a MP4 H.264/AAC con píxeles yuv420p, lado máximo 1280,
metadatos eliminados y faststart. La conversión tiene tiempo máximo 180 segundos,
sin shell y con protocolo de lectura limitado a archivos locales. Si falta el
convertidor o el archivo no es compatible, la carga devuelve un error real y permite
seguir con fotos. La conversión se realiza en la solicitud; dimensionar el timeout
de aplicación/proxy a al menos 210 segundos. El análisis IA de video está desactivado.

Cada carga se deduplica por SHA-256 dentro de la maquinaria; el bloqueo de su fila
impide superar los límites por cargas concurrentes. Se eliminan objetos recién
guardados si falla la transacción. La retención y copias de seguridad operativas
deben contemplar tanto base de datos como medios.

### Local o S3

- Local: `MEDIA_ROOT` debe estar en un volumen persistente, privado y fuera del
  directorio estático. Web y worker deben acceder al mismo volumen.
- S3 compatible: `PRIVATE_S3_BUCKET`, `PRIVATE_S3_ENDPOINT_URL` opcional,
  `PRIVATE_S3_REGION`, `PRIVATE_S3_ACCESS_KEY_ID` y
  `PRIVATE_S3_SECRET_ACCESS_KEY`. Si las credenciales específicas se omiten,
  boto3 puede usar credenciales AWS/rol de servicio. El bucket debe tener bloqueo
  de acceso público y cifrado en reposo administrados por el proveedor.

El código no emite ACL públicas ni enlaces prefirmados. El almacenamiento S3 requiere
su propia prueba real de integración al configurarlo; las pruebas locales no acreditan
la configuración de un bucket remoto.

## OpenAI Responses y revisión humana

`OPENAI_API_KEY` solo vive en el servidor. `OPENAI_MODEL` es configurable; el valor
inicial es `gpt-4.1-mini`, cuyo soporte de entrada de imagen, Responses y Structured
Outputs se comprobó en la documentación oficial. `OPENAI_TIMEOUT` es 90 segundos.
La implementación usa `OpenAI.responses.parse` y modelos Pydantic estrictos.
Envía las vistas JPEG como data URLs, nunca enlaces al almacenamiento ni originales
con metadatos. `store=False` evita almacenar la respuesta para recuperación posterior
por API; esto no equivale a una garantía de retención cero del proveedor.

Referencias verificadas durante implementación:

- [Imágenes y visión](https://developers.openai.com/api/docs/guides/images-vision)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Modelo configurable inicial GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)

El consentimiento IA queda registrado antes de encolar. Los documentos privados y
videos no se envían. `asset_ids` permite reanalizar fotos concretas; `mode=description`
redacta únicamente a partir de datos declarados, sin imágenes. El contexto excluye
contactos, ubicación y notas privadas. El material se trata como datos, nunca como
instrucciones; no se conceden herramientas ni acciones administrativas al modelo.

El esquema contiene título, descripción, categoría sugerida, campos con origen y
estado de revisión, componentes, transcripciones literales, advertencias y preguntas.
No usa porcentajes de certeza. Los datos ilegibles son `null`. Una serie exige una
placa claramente legible de la máquina; no se traslada una serie de motor u otro
componente al equipo. La validación local rechaza referencias a imágenes ajenas y
detecta múltiples valores candidatos de un mismo campo. Structured Outputs valida
la estructura, no la verdad de la lectura: toda sugerencia requiere revisión humana.

Los resultados quedan en `AnalysisJob.result`, con `data` y `provenance` como mapas
de campos aplicables. Nunca modifican automáticamente `Machine`. La aceptación de
campos seleccionados es una operación explícita del usuario y conserva su origen.
El trabajo guarda una instantánea de la entrada: cambios posteriores del usuario
no alteran un análisis ya encolado.

## Cola persistente y consumo

Ejecutar `python manage.py runworker` como proceso supervisado. `--once` procesa un
trabajo y un lote de avisos para diagnóstico; `--poll 3` es el sondeo inicial.
PostgreSQL permite varios workers mediante `SELECT FOR UPDATE SKIP LOCKED`; una
actualización condicional del estado también evita doble reclamo. SQLite solo sirve
para desarrollo local con un worker.

- Estados reales: queued, running, completed, failed. No porcentajes estimados.
- Huella única: máquina, revisión, modo, fotos/hash/propósito, datos, modelo y versión
  de prompt. Repetir la misma solicitud devuelve el mismo trabajo sin otro cobro.
  Un fallo final de la misma entrada tampoco se duplica automáticamente: cambiar
  fotos/datos crea un nuevo trabajo, sujeto a cuotas.
- Reintentos de red, timeout, 429 y errores 5xx: máximo inicial de dos intentos,
  espera exponencial de 30 segundos en el primer reintento. El SDK no hace reintentos
  ocultos. Los errores de validación/configuración terminan el trabajo.
- Lease de trabajo: `AI_JOB_STALE_SECONDS=600` y mínimo 300. Se recuperan trabajos
  interrumpidos con el mismo tope de intentos. Un worker antiguo no puede sobrescribir
  el resultado de una lease posterior.
- Cuotas iniciales: 10 trabajos por usuario/día, 100 globales/día y 200000 tokens
  globales/día, ajustables en administración. Una fila de configuración bloqueada
  serializa admisiones y reservas.
- Reserva conservadora por intento: 9000 tokens más 3200 por imagen; descripción
  reserva 9000. Se reserva para todos los intentos autorizados, por adelantado.
  La reserva no es una predicción de tokens ni un precio. La API devuelve consumo
  real de respuestas completadas; en errores con resultado remoto desconocido se
  contabiliza la reserva del intento conservadoramente. Los trabajos pendientes
  de días anteriores y finalizados hoy también participan en el límite.
- Estos controles limitan la admisión operacional. Un modelo distinto puede tener
  otro coste/tokenización: ajustar la reserva y configurar además un presupuesto
  de proyecto del proveedor. No representan una garantía monetaria rígida.
- Errores públicos y auditoría no incluyen claves, respuestas crudas del proveedor,
  imágenes ni datos de usuario. La auditoría registra tipo de error, intentos y modelo.

El correo de notificación se procesa con bloqueo de fila, máximo tres intentos y
un lote acotado. Estado `sent` significa **aceptado por el backend SMTP**, no prueba
de recepción o lectura. Un corte tras aceptación SMTP pero antes del commit puede
causar un duplicado (entrega al menos una vez). Si falla correo, el aviso interno
permanece en el panel. Validar dominio/remitente y comprobar recepción real antes
de declarar el correo listo en producción.

## PDF y privacidad

`build_pdf` usa ReportLab, texto escapado, fotografías proporcionadas sin deformar,
tablas con salto de página y encabezado/pie. Recibe la misma instantánea revisada
de la ficha web. Con una versión, nunca usa título o datos comerciales del borrador
actual. Disponibilidad se consulta actual para reflejar vendida/retirada.

Una ficha pública exige versión explícita, `public_asset_ids`, autorización vigente
de cada archivo y finalidad distinta de placa/documento. Series y notas internas se
eliminan también del PDF. Contacto requiere consentimiento en la instantánea. Las
versiones internas muestran procedencia y datos privados, y se rotulan como internas.
Los borradores se identifican pendientes de revisión. No se deriva una autorización
de conocer el UUID: las vistas comprueban permisos antes de llamar al generador.

## Verificación

`python manage.py test portal.tests.test_processing` cubre decodificación HEIC real,
rechazo de extensión/contenido falso, deduplicación, límites, propiedad, privacidad de
storage, consentimiento, consumo, schema/placas, formato del request Responses,
ausencia de sobrescritura, reintentos/recuperación, sanitización, correo simulado y
contenido privado excluido de PDF. `pypdf` se usa para inspeccionar el PDF en pruebas.
Mocks de OpenAI y SMTP prueban comportamiento del código, no disponibilidad ni entrega
real. La generación PDF además se revisa visualmente mediante Poppler durante desarrollo.
