# Formulario rápido · Fotos, ficha y envío

## Recorrido del anunciante

1. **Fotos:** cargar las imágenes y pulsar «Preparar mi ficha». El aviso junto al botón explica el envío a OpenAI y el rellenado del borrador. No hay una segunda casilla de IA ni una selección obligatoria de fotografías. Los documentos se excluyen del análisis.
2. **Ficha:** ver el resultado, indicar la ubicación general y enviar a IMC. El precio es opcional. «Editar información», las especificaciones, observaciones de IA y el contacto público están plegados. No es necesario aceptar cada dato generado.

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

## Fallos y edición manual

Una foto guardada no se pierde por un error de IA. La persona puede pasar a edición manual, añadir un título y ubicación y enviar sin completar especificaciones desconocidas. Las cargas pendientes y los cambios sin guardar se resuelven antes de preparar o enviar. Los errores muestran la acción que falta sin añadir pasos nuevos.

## Operación

La migración `0007_automatic_draft_completion` añade metadatos de aplicación a los análisis. No modifica las fichas existentes durante la migración. No requiere nuevas credenciales ni variables de entorno.

La versión integrada pasó **146 pruebas Django, sin omisiones**, con ffmpeg/ffprobe reales. Cubren aplicación por worker, idempotencia, cambios humanos durante el procesamiento, acceso, autorización, privacidad del borrador, recuperación manual y envío duplicado. `check`, migraciones pendientes y la prueba DOM del catálogo también pasaron. Las evidencias del despliegue se registran por separado en el informe de actualización.

La suite de interfaz se conserva en el repositorio: `npm ci --ignore-scripts` y `npm run test:ui`. Usa jsdom sólo para desarrollo y genera una plantilla sintética sin consultar la base de datos. En Windows puede indicarse `PYTHON` con la ruta del intérprete del entorno virtual. GitHub Actions ejecuta esta suite junto a las pruebas de Django.
