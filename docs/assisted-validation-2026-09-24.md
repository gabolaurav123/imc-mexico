# Validación y correcciones de la ficha asistida

Fecha: 24 de septiembre de 2026. Base de trabajo: `5f03e53`.

## Resultado y alcance

Se conserva el módulo Django, su base de datos, el formulario editable, el OCR de
placas, la investigación y las fichas virtual/PDF. Esta entrega corrige siete
problemas localizados en el recorrido de las imágenes y los datos. No añade una
biblioteca, un registro paralelo ni un conector supuesto para la web principal.

El [mapa de campos](assisted-field-mapping-2026-09-24.md) distingue campos locales,
etiquetas públicas observadas y campos privados de IMC todavía no comprobados.

## 1. Recorrido real revisado

| Etapa | Implementación existente | Comprobación / decisión |
|---|---|---|
| Entrada | `ingest_asset`, `save_draft`, `enqueue_analysis` | Original privado, miniatura independiente, hash de contenido, propietario, categoría y revisión del borrador. Subir de nuevo el mismo archivo conserva el adjunto existente. |
| Extracción | `process_analysis` y una llamada visual por fotografía | Placa y foto general siguen siendo entradas válidas. Cada lectura se vincula a su fotografía. Los resultados de una foto no se presentan como lecturas de otra. |
| Normalización | `normalize_analysis`, `_merge_image_results` | Campos tipados y procedencia; valores ilegibles no se completan por intuición. Se exponen los valores cuando las lecturas discrepan. |
| Enriquecimiento | `research_machine`, catálogo técnico y `estimate_machine` | Se mantienen consultas acotadas, fuentes identificadas y validación de modelo/variante. Una referencia de catálogo no acredita año exacto, origen o estado de la unidad. |
| Asignación | `apply_analysis_automatically`, `save_draft` | Se completan campos elegibles de la misma ficha; se preservan ediciones, vaciados manuales y versión del usuario. La descripción se recompone con los datos aceptados. |
| Presentación | Formulario, ficha virtual y PDF existentes | La salida llega a campos editables. No se cambia el diseño ni se añade trazabilidad privada al PDF público. |
| Integración | Exportación aprobada, registro de entregas y resolución de catálogo | Preparados localmente; todavía no existe recepción ni acuse real del principal. |

El proveedor visual configurado sigue siendo **GPT-5.6 Terra** y el modelo de
investigación **GPT-5.6 Luna**, conforme a la política existente. No se utiliza
Astra. La versión del recorrido pasa de `v34` a `v36`, para no reutilizar como
nuevas lecturas la caché anterior a estas correcciones.

## 2. Problemas corregidos

| Problema reproducido | Corrección | Límite que se conserva |
|---|---|---|
| Los recortes de una foto general partían de una imagen ya reducida. | Se recorta desde los píxeles del original cuando éste cabe en los límites existentes; se conserva la miniatura web. | No se reconstruyen letras. Fuente de hasta 12 MiB y 50 MP, recortes de hasta 768 px y 4 MiB en conjunto; alternativa desde la vista preparada cuando procede. |
| Un error intermedio podía dejar sin leer una placa situada después. | Las fotos declaradas como placa se procesan primero, conservando el orden de la galería y sus identificadores. | No se multiplican reintentos remotos cuando hay un fallo del proveedor. |
| Una foto aceptada como máquina y relacionada con maquinaria quedaba excluida de la comparación visual del catálogo. | La selección para comparación utiliza los IDs aceptados y la clasificación de máquina. | Placas, documentos y fotos rechazadas permanecen excluidos. |
| Dos lecturas contradictorias quedaban vacías con un aviso genérico. | El resultado incorpora ambas lecturas acotadas y la interfaz muestra sus valores y fotografías disponibles. | No se escoge ni aplica automáticamente una lectura en conflicto. |
| Añadir un documento durante el análisis invalidaba resultados de fotos que no dependían de él. | El inventario utilizado para comprobar cambios excluye documentos, también al leer instantáneas antiguas. | Se sigue rechazando la aplicación si cambian o desaparecen las fotografías del análisis. |
| Las clasificaciones visuales útiles quedaban sólo en el texto. | Se aplican propuestas guardadas de opciones cerradas del perfil, como orugas, familia y brazo, en sus casillas editables. | Se comprueban fotografía, evidencia y opción válida; no se convierte una propuesta en un dato confirmado ni se aplica así un modelo o una potencia dudosa. |
| La investigación descartaba un modelo parcialmente legible y buscaba otras familias. | Se conserva la pista literal de una foto general aceptada para acotar la consulta y los candidatos. También se permiten recortes nativos de fotos desde 320 px. | La pista no fija identidad ni habilita especificaciones, año o precio. Se excluyen placas, componentes, fotos rechazadas y pistas contradictorias; no se amplían artificialmente los píxeles. |

No se atribuye a estos cambios una mejora porcentual de precisión: los tests
comprueban comportamiento, asignación y conservación; la precisión requiere
evaluar cada campo de casos reales con referencia conocida.

## 3. Investigación del formulario principal

Se recorrió [Publicar maquinaria](https://www.imcmexico.com.mx/registro-de-datos-para-la-publicacion-gratuita-de-maquinaria)
y se envió el primer paso con el correo expresamente indicado por el usuario.
El sitio asignó una contraseña y confirmó el envío del correo de validación;
el mensaje llegó al buzón controlado. No se considera una cuenta activada.

El enlace de validación incluye una contraseña en sus parámetros y se entrega
con HTTP. Al abrir la misma ruta del sitio con HTTPS respondió **«File not
found»**. El acceso normal con la credencial asignada respondió **«Usuario y/o
contraseña incorrectos!»**. No se enviaron nuevos intentos de registro ni se
publicó una máquina. Los informes no conservan credenciales ni enlaces de acceso.

El primer formulario observado contiene `Login` (texto, máximo 100, asterisco
visual), `Sugerencia` (texto de sólo lectura, máximo 10), dos campos de contraseña
inicialmente ocultos y el botón `BTN_Siguiente`. Las tres etapas anunciadas son
Datos de Registro, Finalidad de Publicación y Publicación Concluída. Las marcas
visuales no equivalen a una validación de servidor comprobada.

La [guía pública](https://www.imcmexico.com.mx/guia-para-publicar-gratis) documenta
Venta, Renta, Venta y Renta y Sólo Guardar; menciona Características Técnicas,
cuatro mejores fotografías y Grabar Publicación. Esto no verifica que Sólo
Guardar sea privado ni que cuatro sea el límite técnico vigente. Tampoco revela
IDs internos, campos obligatorios del paso privado o su comportamiento al reabrir.

## 4. Integración mínima que se puede justificar

1. Reparar el acceso del principal y observar un guardado autorizado cuya
   visibilidad esté comprobada.
2. Completar el mapa con los nombres, formatos, obligatoriedad y relaciones
   reales del formulario. Recibir un extracto autorizado de tipo, marca y modelo
   con sus IDs, conservando ceros, variantes y relaciones entre padres.
3. Introducir los datos del módulo mediante el formulario existente o una función
   del servidor que reutilice sus validaciones; elegir el mecanismo tras revisar
   el código/acceso disponible. No se presupone API, SSO ni acceso directo a MySQL.
4. Conservar la relación entre anunciante, UUID local, ID canónico remoto y
   referencia comercial. Registrar el resultado del guardado; un reintento debe
   consultar la misma operación antes de crear otra publicación.
5. Verificar reapertura y consulta. El principal mantiene sus usuarios y catálogo;
   el módulo conserva borradores y análisis. Una edición no debe propagarse en
   ambos sentidos sin una autoridad y una regla de conflictos acordadas.

La integración local ya permite preparar una entrega repetible y rechazar
coincidencias de catálogo ausentes o ambiguas. **No acredita que la base principal
haya recibido datos**. Ningún ID remoto se deduce del número de serie, del folio
local o de los dígitos de una URL.

## 5. Clasificación de cambios

| Clase | Cambio | Impacto y compatibilidad |
|---|---|---|
| Módulo: implementado | Siete correcciones de procesamiento y aplicación. | Conservan pantallas, esquema y funciones anteriores; sin migración de base de datos. |
| Principal: indispensable para validar | Corregir activación/acceso y retirar contraseñas de enlaces/correos. | Debe reutilizar sus cuentas existentes; requiere acceso al código o responsable del sitio. No se modificó desde este proyecto. |
| Principal: indispensable para conectar | Confirmar campos/IDs, permisos, privacidad del guardado y mecanismo de recepción/acuse. | Debe conservar las relaciones y validaciones actuales. Depende del formulario privado y del acceso técnico real. |
| Opcional | Ampliar referencias, proyectos de compra y documentos. | Se mantienen los requisitos anteriores; se aplaza su ampliación para validar primero una ficha útil. |

## 6. Respaldo y reversión

Antes de modificar se creó `backups/assisted-validation-2026-09-24/code-before.bundle`
y se verificó un volcado PostgreSQL `database-before.dump` de 435 954 bytes,
con 372 entradas y SHA-256
`4c37f2bfe367efe8bb9e967667890e17e77fc8131b37e5b5d22fadfbc0149e7f`.
Los respaldos están fuera del repositorio y contienen información privada.

La base previa tenía 62 máquinas, 107 adjuntos, 15 usuarios, 9 versiones y 2
publicaciones. No había IDs principales duplicados. Estos son los valores del
24 de septiembre, no los de la auditoría anterior.

La reversión ordinaria consiste en desplegar de nuevo `5f03e53` o revertir el
commit de corrección. No requiere restaurar la base de datos, porque no se cambia
su esquema. No se debe restaurar un volcado completo encima de actividad nueva
de usuarios para revertir sólo código.

## 7. Evidencia de validación

La suite aislada comprueba fotografías generales, placas, entradas manuales,
combinación de entradas, correcciones concurrentes, campos insuficientes,
contradicciones, modelos ausentes y preservación de permisos/seriales privados.
Son pruebas controladas de comportamiento; sus respuestas simuladas no se
presentan como precisión observada de la IA.

### Pruebas reales en SeeNode

Se crearon dos borradores privados en la sesión autorizada que estaba abierta
en el módulo. Esa sesión corresponde a otro correo que el utilizado para el
registro en la web principal; no se reasignaron propietarios. Los trabajos de
análisis pertenecen al propietario de cada borrador. No se publicó ninguno.

La placa del montacargas se probó con la fotografía original proporcionada. La
primera lectura completó **9 datos legibles**, contrastados con la imagen:

| Campo | Resultado y evaluación |
|---|---|
| Marca | CATERPILLAR; correcta. |
| Modelo | 2EC25; correcto. |
| Serie | Lectura completa conservada en el borrador privado; correcta. |
| Neumáticos delanteros | 21 × 7 × 15; correcto. |
| Neumáticos traseros | 16 × 6 × 10.5; correcto. |
| Inclinación posterior del mástil | 6°; correcta. |
| Ancho de vía | 34.5 in; correcto. |
| Fabricante | Mitsubishi Caterpillar Forklift America Inc.; correcto. |
| Dirección del fabricante | Houston, USA; correcta como dirección, no como origen de fabricación ni ubicación actual. |

La consulta encontró un anuncio de Smith Machinery que coincide con modelo y
serie. Incorporó **7 campos de referencia**, comprobados contra esa página:
peso (7 110 lb sin batería / 10 640 lb con batería), capacidad (5 000 lb), voltaje
(36 V), altura de elevación (188 in), peso de batería (2 900–3 530 lb), capacidad
de batería (1 300 Ah) y longitud de horquillas (48 in). Esto comprueba la
correspondencia con la fuente, no el estado físico actual de la unidad. La
fuente indica año no disponible y precio por consulta: no permite inventarlos.

La fotografía general de la excavadora se probó sin placa ni serie. La primera
lectura identificó CAT y dejó el modelo 320D pendiente por un sufijo poco legible.
Se observaron dos pérdidas reales: cinco clasificaciones visuales no llegaban a
sus casillas y la búsqueda ignoraba el indicio 320D. Ambas motivaron las dos
correcciones adicionales descritas arriba. El número de textos o campos
administrativos generados no se cuenta como precisión técnica.

Se guardaron un título corregido y una serie escrita manualmente conservando
minúsculas en el borrador del montacargas. Se verificó reapertura de la ficha
virtual, carga de la foto sin deformación y ausencia de desbordamiento horizontal
en la comprobación móvil. La repetición tras el segundo parche se registra en
el cierre de esta sección.

El entorno local no tiene clave del proveedor; las ejecuciones reales se hicieron
en SeeNode. Los registros privados de diagnóstico quedan fuera de Git. No se
publican fotos privadas, series completas, contactos ni comprobantes firmados.

## 8. Límites concretos

- Formulario privado de IMC bloqueado por validación/acceso del sitio principal.
- No se recibió el formato adicional del equipo ni el esquema de MySQL.
- No se ha medido el tiempo de captura manual de un operador; no se afirma un
  ahorro de tiempo ni un porcentaje de exactitud.
- La foto general de la excavadora y la placa del montacargas corresponden a
  equipos distintos. No se combinan para presentar una máquina ficticia.
- Un número de serie legible no concede acceso a un registro universal de
  fabricación; datos sin una fuente válida continúan pendientes.
- SeeNode muestra un aviso de saldo negativo. No se compraron créditos ni se
  cambiaron planes; el estado del despliegue debe verificarse por separado.
