# Ficha preparada con búsqueda por serie o modelo

## Experiencia

La acción «Preparar mi ficha» identifica los datos de las fotografías, consulta referencias web a partir de la serie o del modelo identificado y prepara la descripción. El resultado se guarda automáticamente en el borrador. Enviar a IMC no exige completar ubicación, precio ni especificaciones que no se conozcan. Se pueden editar desde secciones opcionales.

La información encontrada en una ficha de modelo se presenta como referencia del modelo. No demuestra la configuración, estado, uso o ubicación actual de una unidad concreta. Una serie de motor no se utiliza como serie de toda la máquina. Si faltan identificadores legibles, no se elige un modelo por semejanza para rellenar especificaciones. El servidor decide el alcance a partir de la evidencia: una etiqueta incorrecta de «serie exacta» sólo puede convertirse en referencia de modelo si la marca y el modelo completos coinciden. Los datos de otra serie se descartan y el año sigue requiriendo serie exacta y fabricante.

## Integración

`POST /api/maquinarias/{id}/analizar/` acepta `research: true`, junto con `consent: true`, `auto_apply: true`, la revisión del borrador y las imágenes. El aviso junto al botón informa de que OpenAI procesa las imágenes y los identificadores se usan en la búsqueda web.

`research` es un booleano estricto y es falso por defecto. Los clientes anteriores continúan con la lectura de imágenes sin activar una nueva finalidad de búsqueda. El trabajo conserva la opción solicitada; el consentimiento de la acción con búsqueda se registra con versión `2026-09-research`. El mero acceso o la consulta del estado no inicia búsquedas nuevas.

En el modo de descripción con investigación, los identificadores ya declarados se consultan directamente y la descripción se compone después; no se paga una primera redacción que se reemplazaría. La reserva de esa ruta cubre la investigación y conserva la contabilización y los consentimientos existentes. El análisis de fotografías mantiene su lectura de imágenes.

La investigación utiliza la herramienta `web_search` de Responses con el modelo ya configurado. La documentación oficial describe la [búsqueda, las fuentes devueltas y la selección obligatoria de la herramienta](https://developers.openai.com/api/docs/guides/tools-web-search). No requiere otra cuenta de buscador. La compatibilidad del modelo se documenta en [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

El resultado incluye `research.status`, el alcance de la coincidencia, campos con procedencia y fuentes. Se conservan enlaces de fuentes realmente devueltas por la herramienta, no enlaces propuestos libremente como prueba. Las fuentes citadas tienen prioridad sobre el resto de los resultados. El normalizador recibe únicamente fragmentos vinculados a una URL recuperada; reconoce citas en líneas consecutivas y conserva la comprobación literal de identidad y valor. Los diagnósticos registran conteos y motivos de descarte, sin guardar la respuesta completa del proveedor. Las referencias y su alcance acompañan a los datos en la revisión y las exportaciones. Las fuentes que revelarían una serie privada se ocultan en las salidas públicas.

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
