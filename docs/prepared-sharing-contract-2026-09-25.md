# Entrada, contacto y ficha compartible

## Entrada

Las nuevas visitas a `/publicar/` pasan por registro o inicio de sesión. La cuenta debe tener correo, teléfono internacional válido y preferencia de contacto antes de crear otra ficha. Los datos completos se reutilizan; los incompletos se solicitan en el perfil y se vuelve al selector de maquinaria. Los borradores temporales existentes conservan sus archivos, capacidad de sesión y mecanismo de reclamación.

La generación requiere un tipo de máquina y al menos una fotografía utilizable o un número de serie. Una descripción o marca/modelo escritos sin serie ni fotografías ya no inician análisis. Si hay imágenes, el servidor siempre elige lectura visual aunque un cliente solicite sólo descripción. Este cambio no modifica trabajos históricos.

## Contrato para compartir

- `GET /api/maquinarias/<uuid>/compartir/`: estado del enlace y autorizaciones previas del propietario.
- `POST` a esa ruta: `{revision, action: "enable" | "disable", include_serial: boolean, include_contact: boolean, asset_ids?: string[]}`.
- Respuesta: `{url, enabled, revision, include_serial, include_contact}`.
- `GET /s/<code>/`: ficha web; `GET /s/<code>/archivo/<uuid>/`: fotografía autorizada para esa instantánea.

Los enlaces nuevos usan 16 caracteres aleatorios (96 bits). Repetir «compartir» actualiza la instantánea manteniendo la dirección. Una revisión posterior queda privada hasta volver a compartir. Deshabilitar rota el código; el enlace revocado no revive. Las fichas publicadas anteriormente tienen un alias corto de 22 caracteres de su UUID original, con los mismos controles de aprobación.

El propietario autoriza una instantánea de hasta diez fotografías: cuatro principales y seis adicionales. Sólo se admiten imágenes listas identificadas como maquinaria o autorizadas administrativamente. Placas, documentos y placas detectadas automáticamente quedan fuera. Las imágenes nuevas todavía sin analizar requieren generar la ficha antes de compartirlas. También puede compartirse una ficha útil generada únicamente a partir de la serie, sin imágenes.

Serie y contacto están excluidos inicialmente. `include_serial` autoriza exclusivamente el número de serie de esta ficha. `include_contact` autoriza el texto de contacto indicado o, si no lo hay, únicamente el canal elegido en el perfil: correo o teléfono. Notas internas, transcripciones y el resto del perfil siguen privados. La consulta desde el enlace corto guarda un lead vinculado mediante esa capacidad, sin exponer fichas por conocer su identificador interno.

## Límites operativos

`PreparedShare` es una tabla nueva; no crea publicaciones, versiones aprobadas ni registros en el catálogo. El PDF continúa reservado al personal autorizado y conserva la verificación de segundo factor. El enlace se cierra ante revisión desactualizada, retirada, eliminación, rechazo, suspensión de anunciante o cambio de propietario. No hay descargas oficiales mediante la ruta corta.

Las fotografías conocidas como ajenas a maquinaria y las contradicciones legibles impiden compartir o enviar esa ficha. La comprobación usa las correcciones actuales y permite resolver el problema. No suspende automáticamente cuentas ni declara fraude. Los controles existentes de presupuesto, límite de análisis y consentimiento siguen aplicándose.

## Plantillas

El contexto de ficha ofrece `main_assets`, `additional_assets`, `asset_base_url`, `essential_fields`, `share_url` y, para fichas preparadas, `share_contact_url`. Los medios se enlazan con `asset_base_url + asset.id + '/'`. El asistente recibe `share_include_serial` y `share_include_contact` para conservar las opciones previas aunque la revisión haya cambiado.

La migración `0020_prepared_share` es aditiva. Las pruebas cubren permisos, CSRF, revocación, cambios de versión, privacidad de medios, serie y contacto opcionales, enlaces anteriores, consulta asociada, datos de contacto y requisito de entrada. No se realizaron llamadas pagadas al proveedor en estas pruebas.
