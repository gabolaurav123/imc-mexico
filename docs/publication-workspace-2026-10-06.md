# Publicación y centro de operaciones · 6 de octubre de 2026

## Resultado funcional

El catálogo sigue acotando tipo, marca y modelo. Para generar una ficha de una unidad es obligatorio aportar **al menos una fotografía útil (general o placa) o una serie escrita**. No se exige aportar ambas. Un modelo del catálogo permite abrir un borrador con referencias; no reemplaza la identificación del equipo.

El propietario conserva sus correcciones, puede añadir fotografías y puede indicar año y precio exactos. La ficha pública mantiene su estructura, omite campos vacíos y no incorpora mensajes internos de investigación.

## Cambios

### Publicar desde el teléfono o la computadora

- Portada con una acción principal y explicación concreta del material mínimo necesario.
- Selección tipo → marca → modelo con buscador y camino alternativo para fotografías o serie.
- El catálogo abre el paso de fotografías/serie; ya no salta a una ficha generada sin datos de la unidad.
- Entrada visual de fotos y serie; botón principal deshabilitado hasta disponer de material y una explicación junto al botón.
- Menú del panel accesible también en pantalla pequeña. Se mantiene acceso a borradores, solicitudes, mensajes y administración.
- Se preservan el logo, los colores de IMC, las herramientas de compartir, las fotos privadas, la edición de datos y el formato final de la ficha.

### Año y precio orientativos

- Los periodos del catálogo deben estar documentados en una misma referencia. No se unen extremos de fuentes diferentes para construir un intervalo sin respaldo.
- La valoración intenta hasta 12 enlaces candidatos para conseguir un máximo de 6 anuncios legibles. Las páginas inaccesibles ya no consumen los 6 lugares destinados a documentos útiles.
- Se mantienen la comprobación de modelo, moneda, mercado y condición, la separación entre anuncios y ventas realizadas, y las restricciones sobre precios de renta, cuotas o piezas.
- Si no puede establecerse un rango, el editor recibe una razón y un siguiente paso específicos mediante `completion.missing_details` (`field`, `code`, `action`). Se muestra dentro de la tarjeta correspondiente a precio o año.
- Las ayudas no ejecutan nuevas consultas por abrir la ficha. Actualizar la investigación sigue siendo una acción explícita; las correcciones manuales se conservan.

**Límite de precisión:** una foto o un número de serie no garantizan que exista documentación pública del año ni anuncios comparables. El sistema busca y aprovecha la información disponible; no asigna cifras inventadas para rellenar un campo. La falta de una referencia se explica al propietario y no se convierte en una afirmación pública.

### Administración

- Centro de operaciones con prioridades: solicitudes en espera, contactos nuevos, análisis fallidos y correos no enviados.
- Accesos a revisión, comunicaciones, base técnica y envío de notificaciones.
- Bandejas de solicitudes: todas, por revisar, cambios solicitados y resueltas.
- Búsqueda y filtros con etiquetas visibles; paginación que conserva la vista seleccionada; limpiar filtros realmente elimina la consulta anterior.
- Los permisos existentes siguen controlando los registros y acciones de cada persona. No se amplía el acceso del personal.
- Se mantienen el historial de acceso, usuarios, conversaciones, métricas reales y retorno desde Configuración al panel.

## Contrato técnico e integración

- No requiere cambios del esquema de base de datos ni modificaciones de la web principal de IMC México.
- `POST /api/maquinarias/catalogo/` crea un borrador orientado por el catálogo y devuelve `requires_unit_evidence: true`; su URL abre el paso 1.
- La API de preparación y la cola interna exigen evidencia. Se revalida después de adquirir el bloqueo de la máquina.
- Una serie vacía, signos sin contenido o expresiones como «no tengo» y «sin número» no cuentan como identificador. Las reglas se comparten con el cliente.
- Una lista explícitamente vacía de archivos significa que no se han seleccionado imágenes; no equivale a omitir el parámetro y usar las disponibles.
- Un borrador de catálogo no se considera analizado por el mero hecho de añadir una serie. Compartir y enviar requieren la preparación correspondiente.
- No se cambian proveedor, modelo de IA ni presupuesto de consumo. No se introduce generación de imágenes ni consultas externas al abrir una página.
- Estilos generales en `portal-workspace.css`; presentación administrativa específica en `admin-workspace.css`. Las reglas de preparación permanecen separadas de la presentación, para su integración posterior.

## Referencias de investigación

- [NN/g: uso de tablas y acciones sobre registros](https://www.nngroup.com/articles/data-tables/): bandejas filtrables, acciones identificables y contexto de navegación.
- [NN/g: aplicaciones complejas](https://www.nngroup.com/articles/complex-application-design/): mostrar opciones en el momento en que son pertinentes.
- [Caterpillar: equipos usados certificados](https://www.cat.com/en_GB/articles/ci-articles/Cat-Certified-Used.html): la inspección y el mantenimiento documentados son distintos de una apreciación fotográfica. La interfaz no certifica el funcionamiento a partir de una foto.

## Verificación y publicación

Las pruebas se ejecutan con SQLite aislado. La revisión visual usa un servidor local, sin claves de IA, trabajadores de procesamiento ni correos reales. Se comprueban escritorio y móvil, los dos caminos de entrada, persistencia y visibilidad de rangos, navegación y filtros administrativos.

- `npm run test:ui`: correcto, incluidas 52 comprobaciones del flujo de preparación.
- `manage.py check`, comprobación de migraciones y generación de archivos estáticos: correctos; no hay migraciones nuevas.
- La ejecución completa detectó fixtures sin serie y expectativas de textos anteriores. Tras corregirlos, las 18 pruebas de política de modelos y las 24 pruebas de contenido e ingreso pasaron; los demás casos de la ejecución completa habían pasado.
- La actualización de contenidos reconoce los textos predeterminados de la versión anterior y conserva las ediciones del personal.
- Revisión visual a 1440 px y 390 px, sin desbordamiento horizontal en el formulario móvil. Los filtros de administración se verificaron también mediante navegación real.

Las capturas de revisión corresponden a la aplicación local; no acreditan un despliegue en SeeNode ni una consulta nueva y pagada a la IA.

El despliegue de SeeNode requiere la sesión del titular. Publicar el código en GitHub no demuestra por sí mismo que el servicio público haya desplegado esa revisión.
