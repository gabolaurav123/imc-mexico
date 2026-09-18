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

### Fotografías relacionadas con maquinaria

La lectura clasifica cada fotografía como maquinaria, material relacionado
(placas y componentes), contenido ajeno o contenido incierto. Una placa válida
sigue siendo útil sin una foto general. Una imagen borrosa no se declara ajena
por la sola falta de una marca, modelo o serie.

Si todas las imágenes son ajenas o no permiten identificar equipo, el trabajo
termina con un aviso específico: no consulta fuentes externas ni genera o aplica
un título, descripción o especificaciones de maquinaria. Conserva el borrador,
sus archivos y las correcciones anteriores. La interfaz vuelve a las fotos para
que el anunciante pueda agregar una imagen útil y preparar la ficha nuevamente.

En lotes mixtos, los datos y observaciones provienen de las imágenes admitidas.
Los archivos descartados del análisis se identifican en pantalla. La exclusión
no borra archivos ni sustituye la revisión editorial de un eventual anuncio.
La aplicación automática y la aplicación manual de sugerencias verifican esta
condición en el servidor. Los análisis históricos sin clasificación conservan
su comportamiento; no se reclasifican ni se gastan tokens al abrirlos.

Desde `imc-vision-research-2026-09-v18`, cada fotografía tiene una llamada de
lectura independiente, ejecutada en secuencia. La misma llamada clasifica y
extrae; el modelo ve una sola imagen y el servidor asigna su UUID. No acepta
referencias a otros archivos ni observaciones contradictorias. Una foto ajena
no comparte la extracción de texto con una placa válida. La clasificación sigue
siendo probabilística y conserva una salida incierta para imágenes poco claras.

Las lecturas se validan individualmente y se combinan antes de ejecutar una sola
investigación externa. Los valores ausentes no borran lecturas legibles de otras
fotos; los valores coincidentes se reúnen y los contradictorios quedan para
revisión. `image_readings` permite auditar las lecturas y su consumo sin guardar
el contenido de la solicitud ni URLs privadas. Las pruebas reales deben comprobar
también lotes mixtos y ambos órdenes de carga.

`OPENAI_API_KEY` solo vive en el servidor. `OPENAI_MODEL` es configurable; el valor
inicial es `gpt-6-astra`, con entrada de imagen, Responses, búsqueda web y Structured
Outputs. El perfil usa `reasoning.effort=low`, añade 3.500 tokens al límite de salida
y a la reserva de cada llamada y permite al menos 120 segundos por llamada.
Los tokens de salida incluyen el razonamiento; se contabilizan una sola vez.
Los límites diarios y la cantidad de búsquedas no aumentan con el modelo.
`OPENAI_TIMEOUT` conserva su valor base de 90 segundos para modelos anteriores.
La implementación usa `OpenAI.responses.parse` y modelos Pydantic estrictos.
Envía las vistas JPEG como data URLs, nunca enlaces al almacenamiento ni originales
con metadatos. `store=False` evita almacenar la respuesta para recuperación posterior
por API; esto no equivale a una garantía de retención cero del proveedor.

Referencias verificadas durante implementación:

- [Imágenes y visión](https://developers.openai.com/api/docs/guides/images-vision)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Modelo GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Migración y parámetros compatibles](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart)

El modelo queda fijado al encolar cada `AnalysisJob`. En una instalación existente,
hay que cambiar también `OPENAI_MODEL` en el servidor y reiniciar web/worker; cambiar
sólo el valor predeterminado del código no sustituye una variable de entorno ya
configurada. Los trabajos anteriores conservan su modelo y sus resultados históricos.
No se hace una sustitución silenciosa por un modelo mini si el proveedor falla.

El consentimiento IA queda registrado antes de encolar. Los documentos privados y
videos no se envían. `asset_ids` permite reanalizar fotos concretas; `mode=description`
redacta únicamente a partir de datos declarados, sin imágenes. El contexto excluye
contactos, ubicación y notas privadas. El material se trata como datos, nunca como
instrucciones. La lectura inicial no utiliza herramientas. La investigación separada
utiliza sólo búsqueda web; no se conceden acciones administrativas al modelo.

El esquema contiene título, descripción, categoría sugerida, campos con origen y
estado de revisión, componentes, transcripciones literales, advertencias y preguntas.
No usa porcentajes de certeza. Los datos ilegibles son `null`. Una serie exige una
placa claramente legible de la máquina; no se traslada una serie de motor u otro
componente al equipo. La validación local rechaza referencias a imágenes ajenas y
detecta múltiples valores candidatos de un mismo campo. Structured Outputs valida
la estructura, no la verdad de la lectura: toda sugerencia requiere revisión humana.

Los resultados quedan en `AnalysisJob.result`, con `data` y `provenance` como mapas
de campos aplicables. El flujo rápido solicita `auto_apply` al pulsar «Preparar mi
ficha», junto al aviso de procesamiento de imágenes. El worker completa el borrador
privado y conserva el origen y estado de lectura de la IA, sin marcarlo como
confirmación humana. Los cambios del usuario y los campos desconocidos se conservan.
Un reanálisis puede refrescar sugerencias anteriores de IA si siguen sin confirmar
y coinciden exactamente con el valor y la procedencia capturados al encolarlo.
Esto incluye título y especificaciones; las ediciones humanas y los resultados
aplicados por otro análisis posterior impiden la sustitución.
El trabajo guarda una instantánea de entrada y registra el resultado de aplicación
para evitar aplicar el mismo análisis dos veces. El envío y la publicación no se
activan al completar el análisis. La API anterior de selección explícita permanece
compatible para clientes anteriores.

La interfaz nueva solicita además `research: true`: busca referencias por serie o
marca/modelo, valida los campos contra las fuentes consultadas y prepara una
descripción a partir de los datos aceptados. Los clientes anteriores omiten esa
opción y no activan búsquedas. Los campos técnicos web conservan su alcance de
modelo o unidad y las citas. [Contrato, privacidad y límites](research.md).

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
  ocultos. Si falla la primera lectura se conserva ese comportamiento. Si falla
  una lectura posterior, se conserva lo leído, se marcan las demás fotos pendientes
  y no se repite automáticamente el lote ni se inicia la investigación externa.
  La interfaz distingue esa interrupción de una foto realmente ilegible.
  Los errores de validación/configuración de la primera lectura terminan el trabajo.
- Lease de trabajo: `AI_JOB_STALE_SECONDS=600` es el mínimo del perfil anterior para una fotografía. Cubre hasta tres búsquedas
  de 65 segundos, dos normalizaciones de 55 segundos y la lectura visual de 90 segundos,
  con margen de 205 segundos para I/O. Si `OPENAI_TIMEOUT` aumenta sobre 90, ese
  exceso se suma al mínimo; cada fotografía adicional añade su timeout al plazo.
  El perfil Astra amplía el plazo para cubrir sus llamadas de hasta 120 segundos,
  incluidas las etapas de investigación y valoración, y añade tiempo por imagen.
  Se comprueban consentimiento, papelera y vigencia del intento antes de cada lectura.
  Se recuperan trabajos
  interrumpidos con el mismo tope de intentos. Un worker antiguo no puede sobrescribir
  el resultado de una lease posterior.
- Valores por defecto del código: 10 trabajos por usuario/día, 100 globales/día y 200000 tokens
  globales/día, ajustables en administración. Una fila de configuración bloqueada
  serializa admisiones y reservas.
- Reserva base conservadora por intento (modelos anteriores): 12200 tokens por imagen; descripción
  reserva 9000. La investigación añade 78000 por intento: hasta tres etapas de búsqueda
  de 14000 y dos normalizaciones de 18000. La segunda normalización sólo es necesaria
  cuando una coincidencia exacta de serie permite recuperar marca/modelo faltantes.
  Los nuevos trabajos de
  descripción con investigación omiten la redacción preliminar y reservan únicamente
  78000. Una fotografía con investigación técnica reserva 90200 por intento,
  más 36000 si se solicita valoración. Con Astra se añaden 3500 por cada llamada:
  15700 por imagen, 95500 para investigación y 43000 para valoración; una foto con
  ambas fases reserva 154200 por intento. Se reserva por adelantado
  para los intentos que caben en la capacidad disponible, hasta el máximo configurado;
  si sólo cabe uno, el trabajo conserva ese tope y no reintenta sin reserva.
  La reserva no es una predicción de tokens ni un precio. La API devuelve consumo
  real de respuestas completadas; si una llamada visual falla sin consumo conocido,
  se estima sólo esa llamada y se suma a las lecturas ya medidas, sin cobrar fotos
  que no se ejecutaron. Una caída del worker sin resultado recuperable conserva
  la estimación del intento completo. Los trabajos pendientes
  de días anteriores y finalizados hoy también participan en el límite.
- Cada trabajo conserva su reserva por intento. Antes de reclamar un trabajo de una
  versión anterior, el worker comprueba la capacidad bajo el mismo bloqueo de
  configuración que las admisiones: amplía su reserva, limita los intentos si sólo
  cabe uno o finaliza sin llamar al proveedor si no cabe ninguno. No aumenta las cuotas.
  Una ejecución antigua interrumpida se contabiliza por su reserva original; sólo
  su próximo intento se reserva según el coste actual.
- La búsqueda usa como máximo una llamada a la herramienta web en cada una de sus
  tres etapas. Las respuestas conocidas acumulan tokens y llamadas; los resultados
  remotos desconocidos acumulan estimaciones conservadoras sin aparentar consumo
  medido. La tarifa propia de la herramienta web no se expresa como tokens y debe
  incluirse por separado en el presupuesto monetario del proveedor.
- Estos controles limitan la admisión operacional. Un modelo distinto puede tener
  otro coste/tokenización: ajustar la reserva y configurar además un presupuesto
  de proyecto del proveedor. No representan una garantía monetaria rígida.
- Errores públicos y auditoría no incluyen claves, respuestas crudas del proveedor,
  imágenes ni datos de usuario. La auditoría registra tipo de error, intentos y modelo.

El worker es un proceso separado de Gunicorn; el timeout HTTP de 240 segundos no
limita estos trabajos. El supervisor permite 20 segundos de salida al detener el
contenedor: un despliegue durante una llamada puede interrumpirla y requerir recuperación
del lease, con consumo remoto posiblemente desconocido. La cola persiste ese intento;
no garantiza que el proveedor deje de procesarlo al cerrar el contenedor.

El correo de notificación se procesa con bloqueo de fila, máximo tres intentos y
un lote acotado. Estado `sent` significa **aceptado por el backend SMTP**, no prueba
de recepción o lectura. Un corte tras aceptación SMTP pero antes del commit puede
causar un duplicado (entrega al menos una vez). Si falla correo, el aviso interno
permanece en el panel. Validar dominio/remitente y comprobar recepción real antes
de declarar el correo listo en producción.

Las notificaciones se renderizan al enviar como `multipart/alternative` (texto y
HTML), dentro de `multipart/related` cuando se incorpora el logo original mediante
CID. El HTML usa tablas, estilos en línea y los colores de IMC; conserva el contenido
editable de las notificaciones con escape HTML. No carga imágenes remotas ni añade
píxeles de seguimiento. Los botones de acceso validan origen, destinatario, token y
vigencia; los botones de seguimiento se construyen desde rutas internas del portal.
Los enlaces vencidos o inválidos fallan sin regenerar ni extender su token. No se
almacena una copia HTML adicional del enlace privado. El registro genera su enlace
después de establecer la sesión inicial, para conservar su validez.

`EMAIL_REPLY_TO` admite un buzón real opcional. El diagnóstico
`python manage.py check_email_config --json` revisa la configuración sin consultar
DNS/SMTP ni enviar correo; ver [Configuración de correo](email-configuration.md).

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

`portal.tests.test_research_worker_budget` verifica reservas de la investigación ampliada,
compatibilidad de trabajos antiguos, rechazo por presupuesto antes de llamar al proveedor,
lease mínimo y ampliado, recuperación acotada, contabilidad parcial y rechazo de resultados
de un worker con lease antiguo. Estas pruebas usan SQLite aislada y proveedor simulado.

Las direcciones de ensayo terminadas en `.invalid` se suprimen antes de SMTP y quedan
como `failed`, con motivo explícito; nunca como entregadas. El indicador `is_test` por
sí solo no impide enviar un correo a una dirección real autorizada.

### Evidencia de la implementación, 15 de septiembre de 2026

Antes del despliegue se realizaron dos llamadas reales a Responses con `gpt-4.1-mini` y una imagen
sintética marcada PRUEBA/SIN INVENTARIO: placa de un motor, serie parcialmente ilegible
y una instrucción impresa que debía tratarse como datos. Ambas respuestas terminaron
en `completed`; la segunda, con validación v2, consumió 3196 tokens de entrada y 645
de salida. Se confirmó placa de componente, ausencia de serie de máquina, valores
nulos para toda serie parcial y ninguna invención de año/potencia/horas. La máquina
siguió en borrador, sin publicación. Las cuentas de ensayo están marcadas `is_test`
e inactivas. Esta prueba valida el circuito real y ese caso concreto; no garantiza
exactitud de todas las fotografías futuras.

En el hosting se completaron otras dos llamadas reales con `gpt-4.1-mini`, una con
placa sintética y otra sin placa. La llamada con placa consumió 3197 tokens de entrada
y 812 de salida. La prueba HTTP verificó clasificación como placa de motor,
serie/año/horas/potencia de máquina sin inventar, aceptación explícita de propuestas,
deduplicación y conservación de ediciones. Se verificaron además cargas HEIC y MOV
con conversión real, rechazo de contenido falso y persistencia tras redespliegue.
Son cuatro llamadas reales en total; las cuentas y fichas de ensayo no constituyen
inventario comercial. La configuración de producción se ajustó a **10 trabajos por
usuario/día, 50 globales/día, 100000 tokens diarios y 2 intentos máximos**.

El PDF de prueba con imagen, título largo, tablas, párrafos y notas internas ocupó
dos páginas, renderizadas con Poppler e inspeccionadas visualmente: sin recortes ni
superposiciones. No se utilizó inventario ficticio como publicación comercial.

Se probó también una conversión real con FFmpeg 9.0.1: video MOV sintético de dos
segundos a MP4 H.264/yuv420p, con conservación del original, resolución sin ampliación
y rechazo al bajar el máximo permitido a un segundo. Las suites de procesamiento,
respaldo e inventario de medios completaron 31 pruebas sin omisiones con ffmpeg y
ffprobe configurados. Incluyen revocación de métricas opcionales durante una llamada
de IA, sin perder el resultado del análisis ni registrar el evento revocado.
