# Publicación por catálogo y ampliación de conocimiento

## Investigación y decisiones

Se revisó el [catálogo de IMC México](https://www.imcmexico.com.mx/catalogo-de-maquinaria) en el navegador. Su selección encadenada de tipo, marca y modelo permite acotar el equipo antes de pedir más datos. Se conserva ese criterio y se añade búsqueda en cada nivel, resultados paginados y acceso directo a fotografías o serie cuando el usuario no conoce el modelo.

La revisión de [RitchieSpecs](https://www.ritchiespecs.com/) y de los [productos anteriores de Volvo](https://www.volvoce.com/global/en/products-and-services/past-products/) mostró la conveniencia de separar identidad de modelo, documentación técnica, periodo y comparables. Un nombre presente en un índice no acredita medidas, precio ni año de una unidad. Los detalles de recuperación y límites de las fuentes están en [catalogue-sources-2026-10-06.md](catalogue-sources-2026-10-06.md).

Para listas extensas se consultaron las pautas de [Home Office](https://design.homeoffice.gov.uk/design-system/patterns/help-users-to/long-lists) y [WAI-ARIA](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/). La implementación utiliza botones y buscadores etiquetados, foco al cambiar de paso, mensajes de resultados y selección explícita antes de generar.

## Funcionamiento entregado

1. Elegir el tipo mediante búsqueda o botones de acceso rápido.
2. Ver inmediatamente las marcas con modelos disponibles para ese tipo.
3. Elegir o buscar el modelo. Los modelos con características documentadas aparecen primero.
4. Pulsar **Generar ficha de maquinaria**. Se incorporan datos locales y se continúa la investigación si la cobertura está incompleta.
5. Editar, agregar fotografías, compartir o enviar a revisión usando la ficha existente.

Desde cualquier paso se puede continuar con fotografías, fotografía de la placa o serie escrita. La selección conocida se conserva para acotar esa identificación. El formato de la ficha terminada no se rediseña.

## Datos

El paquete añade un índice de 10.360 identidades de construcción, pavimentación, elevación y manejo de materiales, y 120 referencias técnicas nuevas de Komatsu. Conserva las referencias anteriores. Los registros de índice tienen `specs: {}` y no generan medidas, años ni precios por sí solos.

En una instalación aislada del paquete se obtuvieron 10.792 modelos seleccionables frente a 545 anteriores: aproximadamente **19,8 veces**. Hay 11.033 referencias de fuente, 560 referencias con especificaciones y 410 con periodo documentado. Estas cifras describen niveles distintos de cobertura; no son 10.792 fichas técnicas completas.

La administración permite filtrar referencias con especificaciones, sólo identidad, periodo o anuncios vigentes. Las fuentes y fechas se conservan internamente. Los valores que faltan se investigan al preparar el modelo; no se inventan para incrementar las cifras.

## Velocidad y coste

- El inicio no descarga el catálogo completo de modelos.
- El endpoint `/api/maquinarias/catalogo/descubrir/` devuelve hasta 25 opciones por página. El GET anterior de catálogo también pagina 25 modelos y expone `page`, `page_size`, `total` y `has_more`; los clientes deben pedir las páginas restantes. Su POST conserva el contrato anterior.
- Búsqueda con espera breve mientras se escribe, cancelación de solicitudes anteriores y caché durante la sesión de la página.
- El editor también carga sugerencias de modelos bajo demanda.
- Las fichas con cobertura local suficiente evitan un trabajo nuevo de análisis.
- Las referencias locales parciales se usan antes de consultar fabricante y catálogos externos.
- El instalador agrupa inserciones y conserva registros modificados por administración.

Medición local con SQLite y el catálogo ampliado: página de marcas de excavadoras, 3 consultas y unos 6,4 KB; página de modelos Caterpillar, 4 consultas y unos 7,9 KB. Son mediciones del entorno local, no una garantía de latencia de internet o del proveedor de IA.

## Integridad e integración

- Tipo, marca y modelo se validan en servidor; modificar campos ocultos no permite atribuir datos a otra máquina.
- Las referencias deben coincidir con la categoría exacta del modelo y estar activas y aprobadas.
- La generación conserva el control de revisiones y la protección de correcciones del propietario.
- El parámetro de generación automática se consume una sola vez; al recargar se retoma el trabajo guardado.
- No se añaden dependencias de la web principal ni cambios de esquema. El módulo conserva sus interfaces de integración existentes.
- `deploy.py` conserva su bloqueo de despliegue, migración e instalación idempotente. Los importadores nuevos generan archivos revisables; no publican anuncios ni acceden a la base maestra externa.

## Verificación

Se comprueban selección dependiente, búsqueda, respuestas tardías, vuelta a pasos anteriores, alternativas de fotos/serie, selección manipulada, paginación, protección de revisiones, reanudación sin duplicar análisis y conservación de modificaciones administrativas. También se revisa el flujo real en navegador de escritorio y de 390 px de ancho con una base SQLite aislada y sin enviar correos ni consumir análisis externos.

Se verificó la generación local de una referencia Caterpillar 320D L con características, rango de años y rango de anuncios ya documentados. Esto no equivale a certificar la configuración ni el precio de venta de una unidad particular.
