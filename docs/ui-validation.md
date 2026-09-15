# Interfaz y validación

## Arquitectura

Templates Django, una hoja CSS y JavaScript nativo. No hay build de frontend, paquete de runtime JavaScript, fuentes remotas ni bibliotecas cargadas desde CDN. Los SVG son ilustraciones esquemáticas propias; no representan inventario disponible.

El asistente envía cambios mediante CSRF y revisiones optimistas. Los archivos usan XMLHttpRequest para mostrar el progreso real de transferencia. La validación y conversión posteriores se muestran como espera del servidor, sin porcentajes simulados. Los fallos conservan las entradas y permiten reintentar. Una revisión concurrente bloquea nuevos guardados para evitar sobrescrituras.

Las propuestas de IA se incorporan únicamente mediante selección explícita. Los datos del componente y de la máquina no se mezclan por renderizar una tabla genérica: la selección usa `result.data`, mientras placas, advertencias y preguntas se muestran por separado. Cada aplicación envía la revisión vigente.

## Comprobaciones realizadas

- `node --check portal/static/portal/app.js`: sintaxis correcta.
- 27 peticiones Django de páginas públicas y privadas: respuesta 200, incluida la ficha con categoría nula, filtros por folio/estado, mensajes, perfil, seguridad, operaciones y revisión. Se usó una transacción de prueba sobre PostgreSQL que se revirtió por completo. El bypass de MFA se limitó al proceso de prueba; no cambió la configuración guardada.
- Pruebas DOM aisladas con HTML realmente renderizado por Django y respuestas de red simuladas: edición durante un guardado envía el siguiente cambio con la revisión recién confirmada; fallo de red conserva entradas y admite reintento; conflicto 409 detiene sobrescrituras; cero horas se conserva; la vista previa refleja el formulario; ausencia de placa permite completar manualmente; análisis exige consentimiento expreso.
- Los componentes incluyen etiquetas visibles, navegación por teclado, enlace para saltar al contenido, estados con `aria-live`, controles de selección individuales y preferencia de movimiento reducido.

Las pruebas DOM no equivalen a una inspección visual. La prueba de navegador local no pudo ejecutarse: IAB devolvió timeout y el navegador conectado bloqueó localhost. Se completó después la inspección visual del despliegue público, descrita a continuación.

## Inspección visual del despliegue público

El 15 de septiembre de 2026 se inspeccionó `https://imc-mexico.seenode.app/` en el navegador Brave conectado. La plataforma respondió correctamente en el navegador aun cuando una ruta de salida del entorno de shell devolvía 502. La primera entrega inspeccionada correspondía al despliegue `1cf4130`.

- Portada de escritorio, aproximadamente 1904 × 854 px: identidad, navegación, llamada principal, ilustración marcada como ejemplo y contenido cargados. Captura mostrada durante la revisión.
- Portada, menú, guía y acceso con viewport 360 × 780 px: navegación móvil operativa y disposición vertical legible. El ancho útil de documento y viewport fue 345 px en ambos casos; la diferencia con 360 corresponde a la barra de desplazamiento.
- Acceso real con una cuenta marcada como prueba; no se expusieron credenciales en capturas. Panel, pasos 1, 2, 3 y 5 del asistente y ficha interna inspeccionados en móvil sin modificar datos. El texto extenso de una maquinaria de prueba se distribuye en varias líneas; los estados y consentimientos permanecen visibles.
- Asistente inspeccionado también a 1440 × 900 px: barra lateral, pasos, indicación de guardado y área de carga correctamente dispuestos.
- Video sintético de prueba, cargado originalmente como MOV y servido en su versión convertida: reproducción confirmada en la ficha, `duration=2`, `readyState=4`, `paused=false`, `currentTime=0.256911` y `error=null`. No se activó ningún análisis de video.
- Consola del navegador sin mensajes de nivel error o warning en la consulta de los últimos 20 mensajes durante la inspección.

La inspección detectó dos defectos de presentación corregidos en el código: el template informativo interpretaba `section.items` como método de diccionario y mostraba sus tuplas; el título de acceso unía palabras al ocultar saltos de línea en móvil. En el despliegue `535c6c6` se confirmó que la guía ya no contiene tuplas ni encabezados vacíos y que cerrar sesión retorna a la portada anónima. La conexión del navegador se perdió antes de repetir la captura móvil del título de acceso y de la pantalla de registro cerrado; esos dos puntos no se presentan como inspeccionados visualmente en esa revisión.

## Contenido configurable

En Contenido del sitio, la clave `home-hero` permite editar el título (con saltos de línea) y el párrafo de la sección principal. Solo texto plano; no ejecuta HTML del administrador. Si la entrada no existe o está inactiva, se utiliza la versión predeterminada.

Las claves de las páginas informativas coinciden con sus rutas: `como-funciona`, `guia-de-fotos`, `preguntas-frecuentes`, `privacidad` y `terminos`.

El teléfono y correo comerciales visibles salen de Configuración de la plataforma. El botón manual de WhatsApp aparece únicamente en fichas públicas autorizadas si el teléfono configurado tiene formato internacional `+` y 8–15 dígitos. Abre un borrador; nunca envía mensajes automáticamente.

## Revisión manual de una entrega

1. En un ancho de 360 px, recorrer registro, panel y los cinco pasos sin desplazamiento horizontal.
2. Cargar una fotografía general, una placa y un video opcional. Revisar su clasificación, reordenar y elegir portada.
3. Interrumpir la conexión durante un cambio y una carga. Reintentar y comprobar que la ficha se conserva.
4. Solicitar IA y aceptar solo un campo. Confirmar que las correcciones no seleccionadas se conservan.
5. Enviar y revisar el folio. Desde Operaciones, autorizar imágenes, revisar al anunciante, decidir la solicitud y comparar versiones.
6. Habilitar la ficha compartible. Comprobar que no muestra datos privados y que consulta, PDF y disponibilidad corresponden a la versión autorizada.
