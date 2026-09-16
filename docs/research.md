# Ficha preparada con serie escrita o fotografías

## Experiencia

La acción «Preparar mi ficha» identifica los datos de las fotografías, consulta referencias web a partir de la serie o del modelo identificado y prepara la descripción. El resultado se guarda automáticamente en el borrador. Enviar a IMC no exige completar ubicación, precio ni especificaciones que no se conozcan. Se pueden editar desde secciones opcionales.

### Lectura completa de placas y ficha técnica

La lectura identifica la maquinaria descrita por la placa. El título y la descripción no describen el soporte metálico, los tornillos ni el color de la etiqueta. La referencia/modelo y cada especificación legible se extraen por separado; para compactación se incluyen frecuencia de vibración, fuerza centrífuga y profundidad de compactación. Las series se transcriben literalmente cuando son legibles: un formato desconocido no prueba que la lectura sea incorrecta, y un carácter realmente dudoso no se completa por conjetura.

El país de fabricación (`country_of_origin`) sólo se completa con una indicación explícita en la placa o una fuente que identifique el modelo y su fabricación. No se deduce de un eslogan, del nombre de la marca o de la sede de un distribuidor. La ubicación actual (`location`) permanece independiente y no se calcula a partir de la serie.

Volver a preparar la ficha puede corregir un título o una especificación generados por un análisis anterior, siempre que el valor y su procedencia no hayan cambiado desde el inicio de la nueva lectura. Los cambios, confirmaciones y borrados explícitos del propietario se conservan. Un resultado anterior tampoco puede reemplazar los datos de un análisis posterior.

Cuando cambia la identidad, las especificaciones web no confirmadas de otro modelo se retiran antes de regenerar la descripción. Sus trabajos e instantáneas históricos se conservan. Las exportaciones tampoco presentan fuentes de una identidad anterior como referencias del modelo actual; una referencia web nunca sustituye una lectura clara de la propia placa.

La vista previa y las exportaciones muestran las especificaciones disponibles aunque no estén configuradas como campos particulares de la categoría. Las fotos identificadas como primeros planos de placas se presentan como evidencia privada. Esta clasificación no modifica el archivo original y queda conservada en la instantánea; la aprobación no vuelve a incluirlas entre las fotos públicas.

La serie es un campo opcional visible en el primer paso: se guarda antes de encolar el análisis, incluso si el usuario acaba de corregirla. No hace falta una foto de placa. Sin serie, una marca y un modelo claramente legibles en fotos generales permiten la misma investigación de modelo.

Si sólo se reconoce el tipo de equipo, se consulta una referencia general de esa categoría. Debe coincidir exactamente con el catálogo permitido; la consulta no utiliza narraciones privadas. El resultado `general_context`, con alcance `category`, conserva enlaces realmente citados, pero `fields` permanece vacío: no se adivinan modelo, medidas ni capacidades. Se muestra en los detalles del análisis, sin convertirlo en especificaciones de la ficha ni de sus exportaciones.

La lectura de fotos devuelve una narración independiente `visual_description` y una lista de rasgos separados `visual_features`, limitados a configuración, accesorios, color y otros rasgos observables. Cada rasgo se filtra por separado para que una frase descartada no elimine las otras observaciones. La descripción final combina el texto válido con los campos aceptados. El servidor descarta frases con series, contactos, cifras técnicas o afirmaciones de funcionamiento; además protege correcciones humanas durante el trabajo. No reutiliza la descripción anterior como sustituto de esa narración visual. Si la imagen no permite identificar nada, conserva un texto neutro y permite enviar las fotos.

La información encontrada en una ficha de modelo se presenta como referencia del modelo. No demuestra la configuración, estado, uso o ubicación actual de una unidad concreta. Una serie de motor no se utiliza como serie de toda la máquina. Si faltan identificadores legibles, no se elige un modelo por semejanza para rellenar especificaciones. El servidor decide el alcance a partir de la evidencia: una etiqueta incorrecta de «serie exacta» sólo puede convertirse en referencia de modelo si la marca y el modelo completos coinciden. Los datos de otra serie se descartan; una frase que niega haber encontrado la serie no constituye una coincidencia. El año sigue requiriendo serie exacta y fabricante.

## Integración

`POST /api/maquinarias/{id}/analizar/` acepta `research: true`, junto con `consent: true`, `auto_apply: true`, la revisión del borrador y las imágenes. El aviso junto al botón informa de que OpenAI procesa las imágenes y los identificadores se usan en la búsqueda web.

`research` es un booleano estricto y es falso por defecto. Los clientes anteriores continúan con la lectura de imágenes sin activar una nueva finalidad de búsqueda. El trabajo conserva la opción solicitada; el consentimiento de la acción con búsqueda se registra con versión `2026-09-research`. El mero acceso o la consulta del estado no inicia búsquedas nuevas.

En el modo de descripción con investigación, los identificadores ya declarados se consultan directamente y la descripción se compone después; no se paga una primera redacción que se reemplazaría. La reserva de esa ruta cubre la investigación y conserva la contabilización y los consentimientos existentes. El análisis de fotografías mantiene su lectura de imágenes.

La investigación utiliza la herramienta `web_search` de Responses con el modelo ya configurado. La documentación oficial describe la [búsqueda, las fuentes devueltas y la selección obligatoria de la herramienta](https://developers.openai.com/api/docs/guides/tools-web-search). No requiere otra cuenta de buscador. La compatibilidad del modelo se documenta en [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

El resultado incluye `research.status`, el alcance de la coincidencia, campos con procedencia y fuentes. Se conservan enlaces de fuentes realmente devueltas por la herramienta, no enlaces propuestos libremente como prueba. Las fuentes citadas tienen prioridad sobre el resto de los resultados. El normalizador recibe únicamente fragmentos vinculados a una URL recuperada y devuelve el índice del fragmento para cada dato. El servidor toma de ese índice la URL y el texto completo, sin confiar en una cita recortada por el modelo; reconoce citas en líneas consecutivas y conserva la comprobación literal de identidad y valor. Los diagnósticos registran conteos y motivos de descarte, sin guardar la respuesta completa del proveedor. Las referencias y su alcance acompañan a los datos en la revisión y las exportaciones. Las fuentes que revelarían una serie privada se ocultan en las salidas públicas.

Cuando el fragmento omite la identidad pero el título real de esa misma fuente citada incluye marca y modelo inequívocos, ese título puede aportar contexto de modelo. La evidencia etiqueta por separado título y fragmento. El valor técnico debe seguir apareciendo literalmente en el fragmento: el título no prueba una serie exacta ni un año, y una identidad distinta o una comparación ambigua impiden usar ese contexto.

## Conservación de datos y fallos

- Las correcciones humanas y los ceros se conservan, igual que en el formulario de dos pasos.
- La búsqueda aporta especificaciones técnicas; no deduce horas, kilometraje, precio, condición, ubicación actual ni datos personales a partir de un catálogo.
- La búsqueda recibe identificadores del equipo, no el contacto ni la ubicación del anunciante.
- Si no se encuentra una coincidencia fiable o el proveedor falla, se conserva lo obtenido de las fotos. El estado indica que la investigación no se completó; la solicitud puede enviarse con información incompleta.
- El envío con datos mínimos dispone de un título y un texto neutros del sistema, sin atribuirlos a una investigación exitosa.
- La publicación permanece sujeta a la revisión de IMC. El permiso de contacto público sigue separado y desmarcado.

## Operación

Las llamadas de visión e investigación comparten la cola, las restricciones de acceso y los límites de consumo existentes. La investigación reserva capacidad y contabiliza sus llamadas, incluidos resultados parciales. Los límites de tokens son operativos, no un tope monetario: las herramientas de búsqueda tienen su propia facturación del proveedor.

No se publican automáticamente las fichas anteriores ni se vuelve a enviar su contenido al proveedor por desplegar esta versión. Se conserva el contenido editorial personalizado; el seed actualiza únicamente los textos iniciales que todavía coinciden exactamente con los predeterminados anteriores.
