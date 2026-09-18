# Ficha preparada con serie escrita o fotografías

## Experiencia

La acción «Preparar mi ficha» identifica los datos de las fotografías, consulta referencias web a partir de la serie o del modelo identificado y prepara la descripción. El resultado se guarda automáticamente en el borrador. Enviar a IMC no exige completar ubicación, precio ni especificaciones que no se conozcan. Se pueden editar desde secciones opcionales.

### Lectura completa de placas y ficha técnica

La lectura identifica la maquinaria descrita por la placa. El título y la descripción no describen el soporte metálico, los tornillos ni el color de la etiqueta. La referencia/modelo y cada especificación legible se extraen por separado; para compactación se incluyen frecuencia de vibración, fuerza centrífuga y profundidad de compactación. Las series se transcriben literalmente cuando son legibles: un formato desconocido no prueba que la lectura sea incorrecta, y un carácter realmente dudoso no se completa por conjetura.

El país de fabricación (`country_of_origin`) sólo se completa con una indicación explícita en la placa o una fuente que identifique el modelo y su fabricación. No se deduce de un eslogan, del nombre de la marca o de la sede de un distribuidor. La ubicación actual (`location`) permanece independiente y no se calcula a partir de la serie.

Volver a preparar la ficha puede corregir un título o una especificación generados por un análisis anterior, siempre que el valor y su procedencia no hayan cambiado desde el inicio de la nueva lectura. Los cambios, confirmaciones y borrados explícitos del propietario se conservan. Un resultado anterior tampoco puede reemplazar los datos de un análisis posterior.

Cuando cambia la identidad, las especificaciones web no confirmadas de otro modelo se retiran antes de regenerar la descripción. Sus trabajos e instantáneas históricos se conservan. Las exportaciones tampoco presentan fuentes de una identidad anterior como referencias del modelo actual; una referencia web nunca sustituye una lectura clara de la propia placa.

Si una nueva lectura de la misma fotografía contradice una cifra de placa o imagen obtenida anteriormente, el sistema conserva el valor previo como dudoso y lo excluye de la descripción automática. El conflicto no desaparece por repetir el análisis: se resuelve con una corrección del anunciante o con una fotografía nueva. Las diferencias sólo de espacios o mayúsculas no son contradicciones. Las imágenes pequeñas se amplían en memoria para facilitar la lectura; esto no recupera detalle perdido ni garantiza una transcripción exacta.

La vista previa y las exportaciones muestran las especificaciones disponibles aunque no estén configuradas como campos particulares de la categoría. Las fotos identificadas como primeros planos de placas se presentan como evidencia privada. Esta clasificación no modifica el archivo original y queda conservada en la instantánea; la aprobación no vuelve a incluirlas entre las fotos públicas.

La serie es un campo opcional visible en el primer paso: se guarda antes de encolar el análisis, incluso si el usuario acaba de corregirla. No hace falta una foto de placa. Sin serie, una marca y un modelo claramente legibles en fotos generales permiten la misma investigación de modelo.

Si sólo se reconoce el tipo de equipo, se consulta una referencia general de esa categoría. Debe coincidir exactamente con el catálogo permitido; la consulta no utiliza narraciones privadas. El resultado `general_context`, con alcance `category`, conserva enlaces realmente citados, pero `fields` permanece vacío: no se adivinan modelo, medidas ni capacidades. Se muestra en los detalles del análisis, sin convertirlo en especificaciones de la ficha ni de sus exportaciones.

La lectura de fotos devuelve una narración independiente `visual_description` y una lista de rasgos separados `visual_features`, limitados a configuración, accesorios, color y otros rasgos observables. Cada rasgo se filtra por separado para que una frase descartada no elimine las otras observaciones. La descripción final combina el texto válido con los campos aceptados. El servidor descarta frases con series, contactos, cifras técnicas o afirmaciones de funcionamiento; además protege correcciones humanas durante el trabajo. No reutiliza la descripción anterior como sustituto de esa narración visual. Si la imagen no permite identificar nada, conserva un texto neutro y permite enviar las fotos.

La información encontrada en una ficha de modelo se presenta como referencia del modelo. No demuestra la configuración, estado, uso o ubicación actual de una unidad concreta. Una serie de motor no se utiliza como serie de toda la máquina. Si faltan identificadores legibles, no se elige un modelo por semejanza para rellenar especificaciones. El servidor decide el alcance a partir de la evidencia: una etiqueta incorrecta de «serie exacta» sólo puede convertirse en referencia de modelo si la marca y el modelo completos coinciden. Los datos de otra serie se descartan; una frase que niega haber encontrado la serie no constituye una coincidencia. El año sigue requiriendo serie exacta y fabricante.

## Integración

### Investigación externa por etapas · versión 2

Con una serie o marca/modelo identificados, la investigación ejecuta **tres consultas independientes**. Una respuesta sin resultados ya no termina el proceso:

1. Si hay serie, busca un registro público de esa unidad. Si falta marca/modelo y una fuente citada los vincula a la serie exacta, valida esa identificación antes de continuar.
2. Consulta documentación del fabricante por marca y modelo. Para marcas con dominio verificado limita las fuentes según la compatibilidad del modelo: utiliza `filters.allowed_domains` de `web_search` cuando está admitido; con la familia `gpt-4.1` dirige la consulta mediante operadores `site:` y comprueba localmente que las fuentes aceptadas pertenezcan a los dominios previstos. Los operadores de búsqueda por sí solos no se consideran una garantía. Para marcas desconocidas busca documentación pública sin inventar un sitio oficial.
3. Contrasta catálogos externos **LECTURA Specs y RitchieSpecs**. Sin serie, el recorrido es fabricante → catálogos → manuales/PDF y distribuidores. Si aún falta modelo, la última etapa busca identificación documental sin atribuir especificaciones de un modelo supuesto.

Las búsquedas de modelo omiten la serie cuando marca/modelo ya están identificados: una serie que no esté indexada no limita esas consultas. La categoría del catálogo aporta vocabulario controlado para evitar homónimos geográficos; no se envían descripción libre, ubicación, notas ni contactos del anunciante. Las seis marcas y las condiciones de acceso están documentadas en [Fuentes públicas](research-sources.md). Se consultan páginas públicas e índices de documentación; **no se ha contratado una API comercial ni abierto registros privados de fabricantes**.

La misma compatibilidad se aplica a las etapas restringidas a catálogos externos. Con `site:`, el servidor descarta las fuentes y los fragmentos que no pertenezcan a un dominio permitido, comparando el dominio completo o un subdominio delimitado. Esta alternativa evita enviar a la familia `gpt-4.1` el parámetro de filtros que `gpt-4.1-mini` rechazó en la prueba real; mantiene el modelo configurado, las etapas y las cuotas. Una consulta sin citas verificables sigue siendo un resultado sin evidencia, aunque termine correctamente.

Cada consulta usa contexto `medium`, una llamada de herramienta y el timeout del perfil de modelo (120 segundos con Astra; 65 en el perfil anterior). Se reúnen hasta 36 fragmentos citados, 18.000 caracteres en total y 800 por fragmento; la normalización final compara la evidencia conjunta, por lo que un dato contradictorio se omite en lugar de ser reemplazado por el último resultado. No se adivinan países ni identificadores. Se reconocen etiquetas explícitas de fabricación en español, inglés, alemán, francés, italiano y portugués, conservando el país literal. «Serie HESSEN 016-9020» puede designar una familia comercial; «Número de serie OTRO123» continúa identificando otra unidad y se descarta.

Un fallo de una consulta permite continuar con las demás y conservar sus datos comprobados. Revocar la autorización o eliminar el borrador impide nuevas llamadas y aplicar datos pendientes. Se registran etapa, dominios consultados, conteos, errores sin texto privado y consumo. Las cuotas existentes se respetan; véase [Procesamiento](processing.md) para reservas y recuperación de trabajos anteriores. Esta actualización no modifica el formulario, las etiquetas ni el diseño de las especificaciones.

`POST /api/maquinarias/{id}/analizar/` acepta `research: true`, junto con `consent: true`, `auto_apply: true`, la revisión del borrador y las imágenes. El aviso junto al botón informa de que OpenAI procesa las imágenes y los identificadores se usan en la búsqueda web.

`research` es un booleano estricto y es falso por defecto. Los clientes anteriores continúan con la lectura de imágenes sin activar una nueva finalidad de búsqueda. El trabajo conserva la opción solicitada; el consentimiento de la acción con búsqueda se registra con versión `2026-09-research`. El mero acceso o la consulta del estado no inicia búsquedas nuevas.

En el modo de descripción con investigación, los identificadores ya declarados se consultan directamente y la descripción se compone después; no se paga una primera redacción que se reemplazaría. La reserva de esa ruta cubre la investigación y conserva la contabilización y los consentimientos existentes. El análisis de fotografías mantiene su lectura de imágenes.

La investigación utiliza la herramienta `web_search` de Responses con el modelo ya configurado. La documentación oficial describe la [búsqueda, las fuentes devueltas y la selección obligatoria de la herramienta](https://developers.openai.com/api/docs/guides/tools-web-search). No requiere otra cuenta de buscador. El perfil predeterminado usa [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), razonamiento `low` y al menos 120 segundos por llamada; las reservas incluyen espacio para razonamiento y salida. Conserva las etapas y los validadores de evidencia.

El resultado incluye `research.status`, el alcance de la coincidencia, campos con procedencia y fuentes. Se conservan enlaces de fuentes realmente devueltas por la herramienta, no enlaces propuestos libremente como prueba. Las fuentes citadas tienen prioridad sobre el resto de los resultados. El normalizador recibe únicamente fragmentos vinculados a una URL recuperada y devuelve el índice del fragmento para cada dato. El servidor toma de ese índice la URL y el texto completo, sin confiar en una cita recortada por el modelo; reconoce citas en líneas consecutivas y conserva la comprobación literal de identidad y valor. Los diagnósticos registran conteos y motivos de descarte, sin guardar la respuesta completa del proveedor. Las referencias y su alcance acompañan a los datos en la revisión y las exportaciones. Las fuentes que revelarían una serie privada se ocultan en las salidas públicas.

Cuando el fragmento omite la identidad pero el título real de esa misma fuente citada incluye marca y modelo inequívocos, ese título puede aportar contexto de modelo. La evidencia etiqueta por separado título y fragmento. El valor técnico debe seguir apareciendo literalmente en el fragmento: el título no prueba una serie exacta ni un año, y una identidad distinta o una comparación ambigua impiden usar ese contexto.

La validación distingue sufijos de variantes, incluso separados por espacios: `420F2 IT` no aporta cifras a `420F2`. Un documento compartido necesita un fragmento que identifique expresamente el modelo consultado. El campo combustible sólo admite nombres explícitos de combustible o energía y combinaciones; las frases de ahorro o consumo no se convierten en su valor. Estas regresiones proceden de la inspección de resultados reales, además de las pruebas simuladas.

Las referencias de identidad admiten frases como «modelo Caterpillar 420F2 IT» y componentes como «motor diésel Caterpillar C4.4». Palabras narrativas breves no son sufijos. Los descartes de identidad registran campo y motivo específico, sin copiar la frase ni los identificadores privados al diagnóstico.

Cuando los resultados incluyen una ficha pública compatible, el servidor también puede leer su tabla directamente: hasta dos documentos de Caterpillar H-CPC o RitchieSpecs, sin una nueva llamada de IA. Exige marca/modelo inequívocos, descarta variantes compartidas y configuraciones opcionales, conserva etiquetas/unidades y somete esas filas a la misma validación y firma. Si el resumen de IA falla, los datos documentales comprobados pueden conservarse. Los límites y el alcance se detallan en `research-sources.md`.

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
