# Mapa de campos para la ficha asistida de IMC

**Fecha:** 24 de septiembre de 2026.  
**Alcance:** adaptar la ficha asistida existente al flujo de publicación de IMC
México. No define un modelo universal de maquinaria ni altera el sitio principal.

## 1. Estado de la evidencia y límite de esta ficha

Este mapa parte del formulario y del contrato locales de este repositorio, de la
auditoría del principal del 23 de septiembre y de la navegación autorizada del
24 de septiembre. «Destino público observado» significa una etiqueta o dato que
un visitante pudo ver; no significa una columna, una API ni una regla SQL del
principal. «Privado pendiente» significa que no se observó el paso de publicación
ya autenticado y, por tanto, no se le atribuye un campo ni obligatoriedad.

| Estado | Hecho comprobado | Consecuencia para esta adaptación |
|---|---|---|
| Público | Las fichas examinadas muestran referencia, tipo, marca/modelo, año, horas cuando existen, precio y moneda, ubicación, fotos, descripción y disponibilidad/venta. | La ficha asistida conserva esos valores como datos separados y sólo propone una proyección aprobada. |
| Guía pública documentada | La [guía para publicar gratis](https://www.imcmexico.com.mx/guia-para-publicar-gratis) nombra la finalidad **Venta**, **Renta**, **Venta y Renta** y **Sólo Guardar**; «Características Técnicas»; «añadir las 4 Mejores Fotografías»; y la acción «Grabar Publicación». Después menciona ver la ficha, enviarla por correo y completar el registro. | Es una guía, no una observación del formulario autenticado funcionando. No prueba que cuatro sea un límite técnico, que «Sólo Guardar» garantice privacidad, ni cuáles validaciones aplica el servidor. |
| Registro inicial | El flujo «Publicar maquinaria» abrió tres etapas visibles: **Datos de registro**, **Finalidad de publicación** y **Publicación concluida**. El primer envío respondió que se remitió una validación por correo. | No prueba que exista una cuenta utilizable ni qué campos pide una publicación de maquinaria. |
| Validación y acceso | El enlace de validación recibido devolvió 404 y el inicio de sesión no produjo una sesión de publicación comprobable. No se cargó ni publicó maquinaria. | Todo destino privado de cuenta, anunciante, máquina, fotos, inventario o anuncio sigue **pendiente de observación autorizada**. |
| Implementación interna | Se observan PHP, sesión PHP y rutas públicas, pero no código, esquema, API, roles ni tablas del principal. | No se generan SQL, rutas de escritura ni IDs remotos por inferencia. |

La incidencia de acceso que impide observar el formulario privado requiere una
reparación en el principal: la validación y la entrega de credenciales deben usar
un flujo seguro y permitir completar la activación. Este documento no modifica
ese sitio. No conserva direcciones de correo, contraseñas, tokens ni parámetros
de enlaces de validación.

## 2. Regla operativa de la adaptación

El formulario local acepta un borrador incompleto y deja que fotos, análisis y
edición propongan datos; el usuario o revisor confirma los que correspondan. La
integración final debe leer el documento privado local, mostrar sus valores en el
formulario real de IMC y guardar mediante una interfaz autorizada del principal.
No se debe hacer que un campo sea obligatorio localmente porque aparezca en una
ficha pública, ni porque un formulario privado todavía no observado pudiera
pedirlo.

| Clase | Fuente local | Regla de protección y entrega |
|---|---|---|
| Cuenta | `User` y sesión local | Identidad, correo y teléfono permanecen privados. El vínculo con IMC exige IDs autorizados; no se empareja por correo, nombre ni empresa escrita. |
| Anunciante | `Machine.owner`, `User.advertiser_status`, consentimientos | El propietario técnico local no acredita vendedor, propietario jurídico ni contacto comercial del principal. La aprobación local habilita revisión, no una cuenta IMC. |
| Máquina | `Machine`, `MachineVersion`, `data`, `provenance`, `Asset` | `Machine.id` es UUID local; una versión aprobada es la única candidata a proyección. Placa, serie, documentos y procedencia quedan privados. |
| Anuncio | `Publication(destination="main")`, `Submission`, disponibilidad | Revisión, entrega, acuse y publicación son estados distintos. `sold` no es compra ni publicación. |
| Identificadores | UUID de máquina, folio, entrega, ID/referencia externos | Cada identificador conserva su dominio. Ninguno se calcula a partir de otro. |

## 3. Campos de cuenta y anunciante

La columna «obligatorio local» describe la aplicación de este repositorio, no el
principal. Un valor «no» puede seguir ser necesario para una operación comercial
una vez que IMC confirme su contrato.

| Clasificación y campo local | Significado / formato local | Obligatorio local | Origen y protección | Destino público observado | Privado IMC pendiente | Transformación y validación antes de entregar |
|---|---|---:|---|---|---|---|
| Cuenta · `User.id` | ID técnico local. | Sí para relacionar el borrador. | Privado; base local. | Ninguno. | ID de usuario/actor IMC. | Guardar una relación explícita `{local_user_id, imc_user_id}` autorizada. Nunca comparar correos para crearla. |
| Cuenta · `User.email` | Correo único normalizado. | Sí para cuenta local. | Privado, verificación local separada. | Ninguno en la ficha observada. | Campo de acceso/contacto y condición de cuenta activa. | No exportarlo en el anuncio. Usarlo sólo mediante el mecanismo autorizado que el principal confirme, con minimización. |
| Cuenta · `User.phone` | Teléfono E.164; el formulario local exige prefijo conocido y 4–14 dígitos nacionales. | Sí al registrarse localmente. | Privado. | Contacto de IMC, sin estructura de almacenamiento observada. | Teléfono de cuenta/contacto y reglas de visibilidad. | Conservar E.164; no publicar ni descomponer sin contrato. |
| Cuenta · `first_name`, `last_name` | Nombre y apellidos. | Sí al registrarse localmente. | Privado. | Ninguno. | Nombre de persona o contacto. | No inferir rol comercial ni persona jurídica. Mapear sólo con consentimiento y campos confirmados. |
| Cuenta · `company` | Texto libre, máximo 180; opcional. | No. | Privado; no es relación. | Ninguno. | Empresa/anunciante y su ID. | Mantener texto original; no convertirlo en empresa del principal ni crearla automáticamente. |
| Cuenta · `contact_preference`, `marketing_consent` | Preferencia de contacto y consentimiento comercial locales. | Preferencia sí en registro; consentimiento comercial no. | Privados y de finalidad limitada. | Ninguno. | Consentimientos/avisos del principal. | No transportar como consentimiento IMC sin texto, versión y finalidad de éste. |
| Anunciante · `advertiser_status` | `pending`, `approved`, `rejected`, `suspended`. | Sí como estado local. | Privado; sólo operador autorizado lo cambia. | Ninguno. | Estado/rol real de anunciante IMC. | No traducir por nombre. Un adaptador debe devolver el estado/ID confirmado del principal. |
| Anunciante · `Consent(kind="advertise"/"contact")` | Autorización local para revisión/difusión y, separadamente, contacto público. | `advertise` sí al enviar; `contact` no. | Registro privado asociado a máquina. | Formulario de contacto público, no su consentimiento interno. | Texto legal, versión y alcance de consentimiento IMC. | Conservar evidencia local; recoger y registrar consentimiento IMC independiente si se exige. |
| Registro público observado · `Login` | Texto máximo 100, marcado obligatorio visualmente en el primer paso. | No aplica al módulo. | El principal asignó una contraseña sugerida; los campos de contraseña estaban ocultos inicialmente. | No forma parte de la ficha. | Regla exacta de alta y activación. | No replicar ni adoptar este mecanismo. El flujo observado no demuestra que una cuenta esté activada. |

## 4. Campos de máquina y ficha asistida

`Machine.data` es la fuente editable; `MachineVersion.data` fija una instantánea.
`provenance` conserva de dónde salió un valor y si requiere revisión. Las columnas
indexadas de `MachineVersion` son una proyección de búsqueda, no otra captura.

| Campo local | Significado / formato | Obligatorio local | Origen y protección | Destino público observado | Privado IMC pendiente | Transformación y validación |
|---|---|---:|---|---|---|---|
| `Machine.id` | UUID estable de la máquina local. | Sí. | Privado/operativo. | No; la referencia pública no lo acredita. | Correlación de origen. | Enviar como `source_machine_id` opaco; nunca sustituirlo por referencia comercial. |
| `Machine.folio` | `IMC-` + primer segmento del UUID; ayuda local. | Derivado. | Operativo local. | No. | Campo interno si IMC lo necesita. | Sólo etiqueta humana; no ID remoto ni llave de deduplicación. |
| `title` | Título hasta 180 caracteres. | Tiene valor por defecto; no identifica técnicamente la unidad. | Editable, con procedencia/revisión. | Título/nombre de ficha, observado de forma comercial. | Reglas de redacción y unicidad. | Usar versión aprobada; excluir título que contenga serie/VIN. |
| `category` / `category_name` | Relación local `Category`; nombre, slug y campos por categoría. | No en el inicio. | Catálogo local, no maestro del principal. | «Tipo de maquinaria». | ID y jerarquía reales de tipo. | Resolver contra un extracto autorizado tipo→marca→modelo; no enviar el ID local como ID IMC. |
| `data.brand` | Marca como texto, máximo de interfaz 120. | No. | Usuario, análisis o investigación; se conserva procedencia. | «Marca». | ID de marca, alias y regla de alta. | Texto original + coincidencia exacta autorizada. Sólo aliases explícitos, por ejemplo no equiparar CAT/Caterpillar sin aprobación. |
| `data.model` | Modelo como texto, máximo de interfaz 120. | No. | Igual que marca. | «Modelo». | ID del modelo y padre válido. | Conservar puntos, decimales y sufijos; coincidencia debe respetar padres tipo/marca. |
| `data.variant` | Variante textual. | No. | Editable y publicable si confirmada. | Puede formar parte del nombre; no se confirmó campo separado. | Campo o regla de variante. | No anexarla/destruirla para forzar un modelo conocido. |
| `data.year` | Año entero local, validado 1800–2200 en servicio; interfaz 1900–2100. | No. | Declarado, leído o investigado con revisión. | «Año». | Obligación y fuente exigida por IMC. | Sólo año exacto confirmado. Nunca usar el centro de un intervalo. |
| `estimated_year_from`, `estimated_year_to` | Intervalo aproximado, enteros 1800–2200 y ordenado. | No. | Privado mientras no haya política de publicación. | No se observó rango en la ficha. | Soporte de rango o texto editorial. | Mantenerlo explícitamente aproximado o no transferirlo; nunca llenar `Año` con él. |
| `data.hours` | Decimal no negativo; `0` es válido si conocido. | No. | Declarado/evidencia/lectura, con origen. | «Horas» cuando se conocen. | Campo, unidad y evidencia aceptada. | Transferir número conocido; ausencia no es cero. Se puede conservar `hours_basis` y fecha como metadatos privados hasta confirmación. |
| `data.description` | Texto hasta 10 000 caracteres en la interfaz. | No para borrador; el servicio genera un texto neutro sólo para permitir revisión cuando falte. | La versión aprobada es publicable; borrador y notas no. | Descripción de la ficha. | Límites, sanitización y campos separados. | Enviar texto aprobado. El texto de sistema no sustituye confirmación comercial. |
| `data.condition` | `Nueva`, `Usada`, `Reacondicionada`, `Para reparación` o vacío. | No. | Declaración/edición local. | Condición no quedó confirmada como campo separado en todos los ejemplos. | Vocabulario de condición. | No traducir a código remoto sin tabla autorizada. |
| `data.preservation_*`, `usage_condition`, `operating_status`, `visible_*`, `attachments`, `applications` | Observaciones de conservación/uso, funcionamiento, defectos, componentes y accesorios. | No. | Pueden provenir de imagen, usuario o revisión. | Descripción y características visibles; no se verificó cada etiqueta. | Campos técnicos/editoriales reales. | Mantener como texto y procedencia; no afirmar condición mecánica por análisis visual. |
| `data.weight`, `data.digging_depth`, `data.power`, `data.capacity` | Texto técnico original. Proyección local opcional a kg, m, kW y m³ cuando la unidad es inequívoca. | No. | Editable y publicable si no contiene dato privado. | Especificaciones variables por ficha; se observaron campos técnicos en catálogo, no contrato de cada categoría. | IDs/campos/unidades por categoría. | Conservar texto y unidad; convertir sólo con medida inequívoca. No forzar columnas inexistentes. |
| `data.location`, `location_country`, `location_region`, `location_city` | Ubicación general, sin dirección particular. | No. | Declarada o cotejada; distinta de origen. | Ubicación de la máquina. | Campos, granularidad y reglas de visibilidad. | No deducir ubicación por IP, fabricante o país de fabricación. |
| `data.country_of_origin` | País de fabricación. | No. | Dato técnico/comercial separado. | No siempre visible. | Campo privado/público. | Mantener separado de ubicación y dirección de fabricante. |
| `data.price` + `data.currency` | Importe decimal y moneda ISO de tres letras; precio sólo es indexable/publicable con moneda explícita. | Precio no; moneda se exige si hay precio válido. | Precio del anunciante separado de valoración. | Precio y moneda (USD confirmado en la ficha examinada). | Autoridad para precio, impuestos, flete y reglas de actualización. | No mezclar monedas ni convertir sin tasa/fecha/política. El precio de IA sólo pasa si una persona lo confirma. |
| `Machine.availability` | `available`, `reserved`, `sold`, `withdrawn`. | Sí, predeterminado `available`. | Estado local separado de revisión. | Disponibilidad, apartada/vendida en catálogo. | Código, autoridad y efecto real en publicación. | Mapear sólo con tabla confirmada. `sold` no crea compra/adquisición ni cambia el estado editorial por sí solo. |

## 5. Identificación, fotos y datos estrictamente privados

| Campo local | Significado / formato | Obligatorio local | Protección | Destino público observado | Destino privado IMC pendiente | Regla de adaptación |
|---|---|---:|---|---|---|---|
| `data.serial`, `data.vin` | Serie/VIN escrito, máximo de interfaz 150 para serie. | No. | Privado. `public_data` lo excluye y evita que aparezca incrustado en título/texto. | No. | Campo privado, permiso y finalidad. | No incluirlo en JSON público ni catálogo. Transferir sólo a un receptor autenticado si IMC confirma el campo y autorización. |
| `data.plate_transcription`, `plate_kind`, `plate_type`, `no_plate` | Transcripción y clasificación de placa. | No. | Privado. | No. | Captura/archivo y permisos privados. | No usar una placa de motor como identificación cierta de toda la máquina. |
| `data.notes`, `research`, `web_research`, comparables y procedencia | Notas, evidencia, investigación y comparables que sustentan una valoración. | No. | Privados y excluidos del contrato público. | No. | Observaciones internas, expediente/evidencia. | No enviarlos al anuncio. El adaptador futuro debe acordar cada metadato privado por separado. |
| Valoración orientativa (`estimate_*`, propuesta de `price`) | Rango/importe orientativo, moneda, fecha y mercado de referencia. | No. | La cifra puede verse en la ficha asistida; evidencia, comparables y base interna siguen privados. | No se comprobó un campo de valoración separado en IMC. | Campo o tratamiento editorial para una valoración. | Mostrarla como orientativa y editable; nunca sustituye el precio solicitado. Sólo un precio confirmado puede proyectarse como precio del anuncio. |
| `Asset.id`, `Asset.original`, `preview` | UUID y bytes privados de imagen/vídeo. | Foto general sí para enviar a revisión; no para crear borrador. | Almacenamiento privado y acceso autorizado. | Galería/fotos. | Endpoint, IDs de medios, tamaños, formatos y derechos del principal. | Nunca enviar rutas internas. Traducir bytes autorizados a la carga real; no inferir nombres o rutas históricas. |
| `Asset.purpose` | `general`, `detail`, `plate`, `document`. | No. | Placa y documento son privados. | Sólo fotos generales/detalle equivalen a galería. La guía documenta «añadir las 4 Mejores Fotografías», sin comprobar el control real. | Clasificación real de adjuntos, cantidad admitida y regla de portada. | Exportar únicamente `general`/`detail`, listos y autorizados. No recortar a cuatro ni tratar cuatro como límite hasta comprobarlo. |
| `public_authorized`, `processing_status`, `position`, `is_cover`, `mime_type`, `size`, `sha256` | Permiso, estado, orden, portada y manifiesto del archivo. | Permiso y estado son requisito de exportación; portada se resuelve de forma determinista. | Privados/operativos; la salida lleva metadatos del archivo emitido. | Fotos y una portada aparente. | Bandera de portada, IDs y validación de medios. | Revalidar autorización justo antes de entregar. Conservar MIME/bytes reales, SHA-256, orden y una sola portada. |

## 6. Campos de anuncio, revisión y entrega

| Campo local | Significado / formato | Obligatorio local | Origen y protección | Destino público observado | Privado IMC pendiente | Transformación y validación |
|---|---|---:|---|---|---|---|
| `Submission.version`, `Submission.status`, mensaje y decisión | Solicitud local sobre una instantánea. | Se crea al enviar. | Privado; revisión local. | Ninguno. | Cola/flujo de aprobación del principal. | No llamar «publicado» a una solicitud ni exportar un borrador más nuevo que la versión aprobada. |
| Finalidad de publicación (sin campo local equivalente) | La guía documenta `Venta`, `Renta`, `Venta y Renta` y `Sólo Guardar`. | No; el módulo no inventa este campo. | No existe dato local para transferir todavía. | Documentado en guía, no observado en formulario privado funcional. | Nombre de campo, valores efectivos, obligatoriedad y efecto de «Sólo Guardar». | Añadir un mapeo sólo después de verificar su contrato. No asumir que «Sólo Guardar» restringe visibilidad o publicación. |
| `Machine.approved_version` | Versión inmutable autorizada por revisión local. | Sí para preparar destino principal. | Privada hasta que se publique por canal autorizado. | La ficha visible es una versión comercial, no su ID. | Regla de revisión principal. | Usar sólo esta versión para proyección y medios; la aprobación local no sustituye aprobación IMC. |
| `Publication(destination="main")` | Registro local del destino principal, separado de ficha compartible. | Se crea al preparar/habilitar flujo local. | Operativo local. | Ninguno. | Identidad del anuncio y estado principal. | `enabled` local no equivale a anuncio creado en IMC. |
| `Publication.status` | `unpublished`, `approved`, `exported`, `published`, `failed`, `disabled`. | Sí como estado local. | Operativo/auditable. | Publicación/estado comercial aparente. | Estados y transiciones reales. | `published` sólo después de comprobar acuse y URL HTTPS, no por tener ID o referencia. |
| `Publication.external_id` | ID canónico opaco, máximo 200. | No hasta recibir acuse. | Operativo local, único para `main` si no está vacío. | No comprobado: referencia visible no prueba esta llave. | ID de anuncio/registro del principal. | Aceptar sólo valor devuelto por receptor; no convertirlo a número ni derivarlo de URL/título. |
| `Publication.external_reference` | Referencia comercial visible, máximo 200. | No. | Operativo local. | «Referencia» de 16 dígitos en fichas examinadas. | Nombre de campo, generación y unicidad. | Mantener como texto independiente, incluidos ceros/prefijos. No asumir que es llave interna. |
| `Publication.external_url` | URL de consulta. | No. | Operativo local; validación restringe a HTTPS en dominio IMC. | URL de ficha pública. | URL canónica/estado de visibilidad. | Es evidencia de consulta, no identificador. Guardar sólo una URL confirmada en acuse. |
| `IntegrationDelivery.id` | UUID de entrega; clave de idempotencia local. | Sí para una entrega preparada. | Privado/auditable. | Ninguno. | Campo de deduplicación del receptor. | Enviar como clave estable; el receptor debe imponer unicidad y permitir consultar por ella tras timeout. |
| `payload_sha256` | SHA-256 del JSON canónico preparado. | Sí. | Privado/auditable. | Ninguno. | Huella/revisión para acuse. | Comparar con acuse; un contenido distinto necesita entrega/versionado coherente. |
| `IntegrationDelivery.payload`, `receipt`, evidencia, estado | Carga preparada, acuse declarado y evidencia; `prepared`/`acknowledged`. | Carga sí al preparar; acuse no. | Privados. | Ninguno. | Contrato de recepción, firma/evidencia y errores. | No declarar un acuse sintético como publicación real. |

## 7. Catálogo: lo que ya funciona y lo que todavía no está conectado

`portal.integration_catalogue.resolve_catalogue` ya sirve para validar una sola
ruta `type → brand → model` contra un extracto que un adaptador autorizado aporte.
No consulta la web, no persiste coincidencias, no crea catálogo ni hace llamadas
al proveedor.

| Comportamiento actual | Estado | Límite para IMC |
|---|---|---|
| Normaliza mayúsculas/minúsculas, acentos, espacios y guiones. | Implementado. | No elimina puntos; `307.5` y `3075` siguen siendo distintos. |
| Conserva IDs opacos de texto, incluso con ceros iniciales. | Implementado. | Los IDs son del extracto autorizado, no IDs locales ni inferidos del HTML público. |
| Exige padres compatibles entre tipo, marca y modelo. | Implementado y falla cerrado ante colisión/ambigüedad. | Falta el extracto real, sus versiones y el mecanismo de consulta del principal. |
| Acepta aliases sólo si se suministran explícitamente. | Implementado. | No hay alias IMC aprobados cargados; no fusionar variantes históricas automáticamente. |
| Informa ausente/ambiguo sin crear nada. | Implementado. | El alta de tipo, marca o modelo sigue pendiente del flujo real del principal. |
| Guarda una coincidencia en IMC o rellena su formulario privado. | No conectado. | Requiere acceso autorizado, contrato de IDs y una operación transaccional del principal. |

## 8. Idempotencia y recepción: estado exacto

La preparación local ya evita crear otra entrega para la misma publicación,
versión y huella de contenido. También separa el ID externo, referencia visible y
URL; rechaza acuses que no correspondan a la máquina, versión, huella, entrega
activa, permisos de foto o anunciante válido.

Eso **no** demuestra idempotencia extremo a extremo. Hoy no hay receptor IMC
conectado, consulta remota por clave, restricción única en el principal ni acuse
real de una publicación. El contrato mínimo que debe confirmar el principal es:

1. recibir `IntegrationDelivery.id` como clave de idempotencia junto con
   `source_machine_id`, versión y `payload_sha256`;
2. crear o actualizar una sola entidad en su propia transacción y persistir una
   correlación única;
3. tras un timeout, devolver el resultado existente para la misma clave en vez
   de crear otra máquina/anuncio;
4. devolver `external_id`, `external_reference`, estado, URL HTTPS y huella o
   versión aceptada; y
5. exponer por separado los errores de catálogo, identidad, permiso de fotos y
   validación del formulario real.

## 9. Decisiones de implementación para la ficha asistida

1. Mantener el inicio ligero: categoría, serie o placa y fotos son ayudas; el
   borrador puede existir sin marca, modelo, año, precio ni foto.
2. Pedir foto general antes de revisión local, no convertirla en un supuesto
   requisito del formulario privado de IMC.
3. Mostrar como campos separados los datos públicos observados: tipo, marca,
   modelo, año, horas, precio+moneda, ubicación, descripción, disponibilidad y
   galería. Mantener visible la valoración orientativa de la ficha asistida,
   claramente distinguida del precio solicitado; ocultar por defecto serie,
   placa, documentos, investigación, notas, evidencia y comparables internos.
4. Llevar al adaptador sólo una `approved_version` y el manifiesto de medios
   autorizados. Si IMC obliga un dato desconocido, devolver un error de campo a
   la ficha; no completar una cifra, una empresa o un ID por aproximación.
5. Mantener la sesión local para proteger borradores mientras se repara y
   observa el acceso del principal. La adaptación mínima puede usar el
   formulario real o un receptor que IMC autorice cuando su contrato esté
   disponible; no presupone SSO ni una API concreta.

## 10. Información requerida para cerrar el mapa sin adivinar

Cuando el flujo privado esté operativo y exista autorización, registrar una
muestra de prueba sin datos comerciales reales y confirmar: nombres de campos,
etapas, obligatoriedad del servidor, validaciones, IDs y jerarquías del catálogo,
finalidad de publicación, reglas efectivas de fotos, visibilidad/contacto, estados
de anuncio, roles, relación usuario–empresa, respuesta de creación/actualización
y consulta por clave de idempotencia. Hasta entonces, cada destino de esta
columna permanece pendiente.
