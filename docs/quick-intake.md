# Formulario rápido · Fotos, ficha y envío

## Recorrido del anunciante

1. **Fotos:** cargar las imágenes y pulsar «Preparar mi ficha». El aviso junto al botón explica el envío a OpenAI, la búsqueda mediante los identificadores de la máquina y el rellenado del borrador. No hay una segunda casilla de IA ni una selección obligatoria de fotografías. Los documentos se excluyen del análisis.
2. **Ficha:** ver el resultado y enviar a IMC. La ubicación, el precio y los detalles técnicos son opcionales. «Editar información», las especificaciones, observaciones de IA y el contacto público están plegados. No es necesario aceptar cada dato generado.

El botón de envío registra la autorización del anunciante para revisión y preparación del anuncio. La publicación continúa bajo control de IMC. El contacto público conserva su autorización opcional separada, desmarcada por defecto.

## Rellenado y conservación de datos

La API acepta `auto_apply: true` en la petición de preparación junto con consentimiento y revisión de borrador. `AnalysisJob` guarda una instantánea para la aplicación y su resultado. El worker incorpora los campos aplicables en el servidor, aunque el navegador se haya cerrado.

- Completa huecos y conserva los datos escritos o corregidos por la persona, incluidos los valores cero.
- Los resultados desconocidos, ambiguos y las series de componentes no se convierten en especificaciones de la máquina.
- La procedencia y el estado de lectura siguen siendo de IA; el rellenado no se registra como confirmación humana.
- Los cambios en fotografías, propietario, autorización o estado de edición se comprueban antes de aplicar.
- Cada resultado se aplica una sola vez. Repetir una consulta o reabrir la ficha no repone un campo que se corrigió o borró.
- Los análisis anteriores pueden completar huecos sin una nueva llamada a OpenAI cuando conservan una revisión compatible. Si cambiaron los datos, se conserva la edición actual.
- El navegador guarda sólo campos modificados y coordina la revisión del servidor con el autocompletado. Los conflictos ajenos a ese análisis conservan las entradas en pantalla.

El resultado puede consultarse en la API de estado del análisis. La API anterior de aplicación por selección sigue disponible para clientes anteriores; el asistente nuevo no la exige.

## Referencias externas y fuentes

Con la autorización de investigación se buscan la serie legible de la máquina o la marca y el modelo identificados. Las fuentes normalizadas se firman en el servidor y sólo completan huecos de marca, modelo, potencia, peso, capacidad, dimensiones, combustible, motor o transmisión. Un año requiere coincidencia con la serie exacta y una fuente de fabricante reconocida. Nunca se rellenan desde la web ubicación, horas, precio, condición ni la serie.

Las referencias conservan la etiqueta «Referencia del modelo; confirmar en este equipo» o «Referencia de la unidad; sujeta a revisión». Una corrección humana de la identidad durante el análisis impide aplicar referencias de la identidad anterior. La descripción se prepara a partir de los campos finalmente aceptados, por lo que no recupera sugerencias descartadas.

La versión enviada conserva una copia privada del manifiesto firmado. La ficha web, el PDF y el JSON del ZIP incluyen únicamente citas verificadas de sus valores publicados. Los enlaces son clicables cuando no contienen identificadores privados; si el título o la URL contiene una serie privada, se muestra «Fuente privada» sin sustituir el enlace por una dirección inventada. El manifiesto, la serie de consulta y la evidencia interna no se incluyen en las referencias públicas.

La verificación usa la clave de firma de Django. Una rotación de `SECRET_KEY` debe conservar la clave anterior mediante el mecanismo de claves de respaldo de Django durante la transición; de lo contrario las pruebas históricas dejarán de verificarse y sus referencias se omitirán hasta resolver la rotación. No se consideran válidas por defecto.

## Fallos y edición manual

Una foto guardada no se pierde por un error de IA. La persona puede enviar las fotos recibidas sin completar especificaciones desconocidas. Si faltan título o descripción y no existe una corrección humana, el envío usa textos neutros de preparación, identificados como pendientes de revisión; no inventa ubicación, año, horas ni condición. Las cargas pendientes y los cambios sin guardar se resuelven antes de preparar o enviar. Los errores muestran la acción que falta sin añadir pasos nuevos.

## Operación

La migración `0007_automatic_draft_completion` añade metadatos de aplicación a los análisis. No modifica las fichas existentes durante la migración. No requiere nuevas credenciales ni variables de entorno.

Esta ampliación pasó **190 pruebas Django, sin omisiones**, con ffmpeg/ffprobe reales, y **16 grupos de pruebas de interfaz**, además del catálogo. Las comprobaciones de configuración y migraciones no detectaron problemas. Las pruebas cubren aplicación por worker, idempotencia, cambios humanos durante el procesamiento, acceso, autorización, privacidad del borrador, envío sin campos manuales obligatorios y fuentes en web/PDF/ZIP.

La suite de interfaz se conserva en el repositorio: `npm ci --ignore-scripts` y `npm run test:ui`. Usa jsdom sólo para desarrollo y genera una plantilla sintética sin consultar la base de datos. En Windows puede indicarse `PYTHON` con la ruta del intérprete del entorno virtual. GitHub Actions ejecuta esta suite junto a las pruebas de Django.
