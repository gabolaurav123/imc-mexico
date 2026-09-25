# Entrega técnica: preparación de maquinaria e IMC México

Fecha: 25 de septiembre de 2026. Proyecto existente `gabolaurav123/imc-mexico`.

## Resultado y alcance

Se conserva el módulo Django, sus rutas, fichas, archivos, permisos, lectura de placas, edición y administración. La mejora adapta ese mismo flujo a la referencia «Publicación de maquinaria». IMC México sigue siendo el destino de una captura **manual**: este cambio no escribe en su base, no publica anuncios en el portal principal y no incorpora una sincronización oculta.

### Recorrido del anunciante

1. Elige el tipo de máquina —con búsqueda en español e inglés— y responde si tiene serie o placa. Puede continuar sin ellas.
2. Sube las fotos disponibles o declara los identificadores que conoce. No necesita cuatro fotos para comenzar.
3. «Completar con IA» reutiliza la lectura individual de imágenes, la investigación externa y la base técnica. La misma ficha recibe los campos propuestos, sin sustituir las correcciones humanas.
4. Puede editar año exacto o rango, horas, ubicación, descripción, características y precio. Precio solicitado y estimación permanecen separados; desconocido no se convierte en cero.
5. El visitante conserva temporalmente su primer resultado y después crea una cuenta o inicia sesión. Se reclama la **misma máquina**, con los mismos archivos y análisis.
6. Envía la ficha a revisión. Una ficha autorizada se comparte mediante enlace web con carrusel y acceso al catálogo de máquinas similares.

El borrador de visitante dura 24 horas, admite tres imágenes y un análisis, y tiene límites por sesión/IP. No autentica al visitante como la cuenta técnica interna. La limpieza respeta fichas reclamadas y análisis en curso. Fotos de placa, documentos y observaciones para IMC siguen siendo privados.

### Estructura de la referencia

Se mantienen cuatro grupos: fotografías principales; datos del equipo; información adicional; fotos adicionales. Se conservan cuatro vistas principales como objetivo de publicación y hasta seis adicionales en el paquete de destino. El historial de archivos no se elimina para cumplir ese límite.

Los campos de tipo, marca, modelo, serie, precio/moneda, año, horas, país, estado y ciudad se guardan por separado. Las observaciones para IMCMEXICO no forman parte de la descripción pública. El botón final indica revisión local; no promete una publicación remota.

## Base de conocimiento ampliada

El paquete versionado pasó de **35 a 85 referencias**, y de **112 a 316 especificaciones**. Se agregaron 50 referencias respaldadas por documentación oficial de Cat, JLG y Toyota: excavadoras, compactadores, minicargadores, montacargas, motoniveladoras y plataformas elevadoras.

Se incorporaron 19 campos técnicos estructurados, entre ellos caudal hidráulico, cilindrada, longitudes de pluma/brazo, fuerzas de excavación, dimensiones de tambor, altura de plataforma, alcance y capacidad de tanques. Los alias exactos documentados permiten encontrar modelos equivalentes sin mezclar variantes o generaciones. La región del documento también condiciona su uso.

Esta base aporta referencias **del modelo**, no inventario disponible ni certificación de una unidad. No se añadieron precios, años de fabricación ni países de origen inventados. El número de serie no es un decodificador universal: el origen requiere placa/documentación o una fuente válida del fabricante. La ubicación actual debe ser declarada por el propietario.

Detalles y fuentes: [ampliación del catálogo](catalogue-expansion-2026-09-25.md) y [matriz de campos](reference-field-mapping-2026-09-25.md).

## IA y precisión

El modelo predeterminado se fija en **`gpt-6-luna`** para imagen, extracción e investigación. Se conserva Responses API con salida estructurada, esfuerzo de razonamiento bajo —medio en lectura de placa—, límites de consumo y `store=false`. Astra permanece bloqueado; no hay cambio silencioso de modelo si Luna falla. Los trabajos antiguos conservan su política registrada.

Se verificó la documentación oficial del modelo: <https://developers.openai.com/api/docs/models/gpt-6-luna>. La disponibilidad efectiva con las credenciales del proyecto también se comprobó en producción: la prueba real registró `gpt-6-luna` tanto como modelo solicitado como modelo respondido. Esto acredita acceso al proveedor; no garantiza una lectura perfecta de cada imagen.

La congruencia distingue compatibilidad, contradicción y evidencia insuficiente mediante comparaciones reales entre lo declarado y lo leído. Una placa de motor no se toma como identificación de la máquina. El resultado muestra el corte temporal del análisis y se retira de la interfaz si cambia la identidad. Un fallo de acceso al modelo conserva la ficha y ofrece un mensaje específico sin exponer detalles del proveedor.

## Recorrido administrativo y exportación

- Usuarios: contador de fichas con enlace al listado filtrado por propietario; las cuentas técnicas temporales quedan excluidas.
- Revisión: aprobación de una versión concreta, evidencia y decisión humana sobre posibles duplicados locales. Compartir modelo no demuestra duplicación.
- Preparación IMC: selección de fotos independiente de la ficha compartida, identificación del anunciante de destino y revisión manual de duplicados con responsable, fecha, resultado, evidencia y límites.
- Entrega: bloques para copiar y ZIP con TXT, PDF administrativo, cuatro fotos principales, hasta seis adicionales, videos autorizados y manifiesto de versión. El PDF usa exactamente los medios seleccionados para el paquete.
- Acuse: referencia y URL reales de IMC sólo después de la captura comprobada. Descargar no cambia la ficha a publicada; los cambios posteriores requieren una actualización manual.

PDF y ZIP requieren permisos administrativos y MFA donde está habilitado, también llamando directamente a sus endpoints. Los usuarios normales comparten la ficha web. Esto no pretende impedir capturas o impresión del navegador.

Se creó un paquete QA mediante la ruta real, en una base local aislada, con una foto autorizada y datos explícitamente de prueba. Se comprobó la versión, el bloqueo antes de la revisión manual y la exclusión de notas y archivos privados. Se renderizó e inspeccionó el PDF. No se publicó una máquina ficticia.

Más detalle: [preparación administrativa](manual-imc-preparation-2026-09-25.md) y [borradores temporales](guest-drafts.md).

## Qué se comprobó en IMC México

En el navegador se revisó la página pública «Solicitud de Maquinaria»: tipo, marca y modelo dependientes, presupuesto/moneda, intervalo de año, horas y observaciones; alquiler añade condiciones de ubicación y duración. Se observaron aproximadamente 66 tipos, 20 marcas bajo excavadoras hidráulicas y 160 opciones de modelos al seleccionar Caterpillar.

Ese recorrido es una **solicitud de compra**, no prueba de las reglas del formulario privado de publicación. Sirvió para separar catálogos y campos estructurados. No se copió su inventario ni se dedujo su esquema interno de MySQL a partir de los selectores.

La activación de la cuenta de prueba en el portal principal no quedó operativa: la ruta de verificación observada devolvió un error y no se comprobó acceso al alta privada. Por tanto, siguen pendientes sus obligatorios definitivos, permisos para publicar por otro anunciante e identificadores internos. El módulo satelital funciona sin esa dependencia.

## Validación y despliegue

La suite completa de cierre pasó **1.049 pruebas y 1.423 subpruebas**; una prueba de conversión real de video se omitió por falta de FFmpeg/FFprobe local. La corrección de invalidación de una revisión manual anterior pasó además sus 22 pruebas focalizadas. Las suites de interfaz, incluyendo visitante, edición concurrente, carga, contraseña y notificaciones, terminaron sin errores. `check`, migraciones pendientes y revisión de diferencias: correctos.

La verificación final incluye las tres franjas de placa, la protección frente a documentos privados y URLs externas, y la persistencia de los nuevos campos técnicos desde la salida de IA hasta la ficha editable. Se corrigió una prueba que todavía esperaba la antigua exclusión de las placas del recorte.

Se verificó la ficha en un ancho móvil de 390 px sin desbordamiento horizontal y sin enlaces PDF para visitante. La prueba local no se cuenta como una llamada real a OpenAI.

Antes de modificar se guardaron un bundle Git y un respaldo PostgreSQL verificado. Las migraciones 0017–0019 son aditivas; conservan registros y relaciones existentes. El despliegue serializa migraciones y carga el paquete técnico versionado, activando únicamente sus nuevas referencias curadas. Las importaciones manuales permanecen pendientes de revisión.

Destino verificado en SeeNode: aplicación `974953`, repositorio `gabolaurav123/imc-mexico`, rama `main`, dominio <https://imc-mexico.seenode.app>. El portal principal no forma parte de este despliegue.

## Estado y siguiente fase

**Implementado y probado localmente:** flujo de visitante, conservación de ficha, edición, campos, catálogo, permisos, congruencia, selección por destino, revisión y paquete manual.

**Preparado pero pendiente de comprobación externa:** publicación privada real en IMC y relación autorizada entre anunciante local y cuenta de destino.

**Integración futura:** acordar identificadores, catálogo, propiedad de datos, roles, medios, disponibilidad y estados con el responsable del sistema principal. Sólo con ese contrato y acceso real se podrá decidir API, MySQL o SSO. No se ha presentado esa fase como implementada.


## Comprobación real de despliegue

El commit `e31555e` se desplegó en el servicio verificado y pasó GitHub Actions (ejecución 36104952682). Posteriormente se comprobó activo `2d1f457`, con la mejora de lectura de placas y el control de un único análisis por borrador visitante. Su ejecución de CI detectó únicamente la expectativa anterior sobre recortes descrita arriba. Se comprobaron en PostgreSQL la migración 0019, **85 referencias aprobadas activas y 316 especificaciones**. Los 16 usuarios normales previos permanecieron; las pruebas crearon dos borradores temporales privados, sin publicar.

Las pruebas por la API pública del módulo cargaron la placa autorizada y completaron el trabajo con modelo solicitado **y respondido** `gpt-6-luna`. Reabrir el borrador devolvió 200; otra sesión recibió 403; no se ofreció exportación PDF. La primera lectura recuperó la serie y el fabricante, pero omitió medidas legibles. Se añadió lectura por tres franjas junto con la imagen completa, dentro de una misma llamada visual y sin cambiar de modelo.

La segunda prueba real, ya con `2d1f457`, recuperó neumáticos delanteros **21 × 7 × 15**, traseros **16 × 6 × 10,5**, inclinación posterior máxima del mástil **6°** y la medida rotulada «LOAD TIRE TREADWIDTH» de **34,5 pulgadas**, además de fabricante, dirección del fabricante y serie. La dirección «Houston, USA» se conserva como dirección del fabricante; no se convierte en país de fabricación ni ubicación actual del equipo.

**Límite observado:** la segunda lectura propuso `2EC2` como modelo y lo etiquetó como lectura clara, mientras que la revisión de la foto permite considerar `2EC25`. La aplicación no detectó automáticamente esa ambigüedad: el propietario debe corregir o confirmar el modelo, conservando la procedencia «lectura de placa» y la edición disponible. La investigación externa terminó sin resultados útiles para completar ese modelo. No se logró identificación exacta ni se obtuvo año o precio estimado con esta foto. La mejora recupera más datos legibles, pero no demuestra que baste una sola placa para completar todos los campos. No se añadió un decodificador supuesto ni un cambio de modelo para ocultar esta limitación. El resultado detallado se conserva como evidencia QA privada, sin incluir la serie ni los enlaces privados en este informe.

Las pruebas visuales se realizaron en el servidor local con navegador real, incluyendo compartir enlace, carrusel y navegación al catálogo. Brave bloqueó la navegación al dominio público con `ERR_BLOCKED_BY_CLIENT`; no se cambió su protección. La comprobación de producción se hizo como prueba de API, no se presenta como recorrido visual remoto completado.
