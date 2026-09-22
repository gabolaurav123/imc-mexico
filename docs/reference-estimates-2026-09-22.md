# Corrección de fichas y referencias — 22 de septiembre de 2026

## Comportamiento

- El inicio pregunta primero por el tipo de máquina y la disponibilidad de serie o placa. Sin serie, ofrece continuar con fotografías generales; la carga aparece después. El análisis muestra un estado de espera y permite recuperar errores.
- El PDF elimina procedencia interna y mensajes de revisión. El resumen ocupa la portada; estado aparente, componentes y aplicaciones comienzan juntos en la segunda página, incluso con descripciones largas. Mantiene cifras estimadas bajo etiquetas explícitas y omite valores pendientes.
- La consulta técnica usa una llamada de búsqueda por etapa para conservar capacidad para catálogos y extracción. La valoración también limita la búsqueda a una llamada. Si la respuesta supera su reserva, la extracción literal de páginas ya recuperadas puede aprovechar evidencia suficiente sin otra llamada de pago.
- Una especificación general de catálogo, como el motor, ya no se convierte automáticamente en una restricción obligatoria de configuración de la unidad para valorar anuncios.
- El precio sugerido se obtiene de su propio campo. Nunca toma el precio de publicación y su moneda del propietario.

## Base de datos

La migración `0014_market_reference` incorpora referencias de mercado vinculadas al catálogo: precio, moneda, país, condición, tipo de precio (anunciado/vendido), año, horas, fecha, evidencia e identidad de la unidad del anuncio. Los registros nuevos requieren revisión; la semilla de esta versión usa una lista explícita con SHA-256 y conserva modificaciones administrativas.

La biblioteca añade siete referencias de compactadores de Wacker Neuson, BOMAG, HAMM y Dynapac. Los campos de ancho de trabajo, peso máximo, tambor y emisiones tienen casillas independientes. Los catálogos regionales y variantes no se aplican indistintamente a cualquier unidad.

Para CAT 320D L se registra el periodo de catálogo 2006–2014, separado de las especificaciones oficiales de la variante NACD 2007. El periodo orienta el año aproximado; no establece el año exacto de una unidad.

El primer conjunto de mercado contiene dos anuncios distintos de CAT 320DL usados en Estados Unidos: USD 66.900 y USD 75.900, observados el 22/09/2026. La mediana es USD 71.400. Son precios solicitados de dos unidades de un mismo anunciante; no son ventas realizadas ni una muestra amplia. No se convierten a MXN ni se ajustan por funcionamiento, horas o apariencia.

La valoración reutiliza referencias aprobadas de hasta 30 días para el modelo exacto, sin llamadas de IA. No mezcla países, monedas, condiciones o precios anunciados con ventas. Los registros vencidos permanecen en el historial administrativo y dejan de producir valoraciones automáticas.

## Reparación de borradores existentes

`python manage.py refresh_library_reference UUID` previsualiza campos disponibles sin modificar datos. `--apply` crea un resultado nuevo de biblioteca, con cero tokens y el registro de aplicación habitual. Exige borrador editable, identidad clara, consentimiento vigente y las mismas imágenes que un análisis pertinente anterior. Las correcciones del propietario conservan prioridad; no publica la ficha.

## Límites

La cobertura es un catálogo inicial verificable, no todas las máquinas del mundo. No se asigna un valor o año sin evidencia. Las fuentes y comparables permanecen en la administración; no se imprimen en el PDF. Esta entrega no incorpora un sistema nuevo de comparación visual mediante fotos de catálogo.
