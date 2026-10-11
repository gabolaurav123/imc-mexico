# Modelo de análisis y búsqueda

Desde el 11 de octubre de 2026, la política predeterminada usa **GPT-6 Luna**
(`OPENAI_MODEL=gpt-6-luna`) para lectura visual, búsqueda y texto mediante Responses.
Admite imágenes, salida estructurada y búsqueda web. Astra sigue bloqueado por la
preferencia expresa del propietario. Los trabajos históricos conservan sus modelos;
los antiguos GPT-5.6 Luna mantienen Terra para visión cuando así quedó registrado.
No se reintenta automáticamente con un modelo más caro.

## Perfil y consumo

- Razonamiento `low` en GPT-6 Luna; las placas históricas con Terra conservan `medium`.
- Una lectura por foto, sin comprobación visual pagada previa que bloquee el botón.
- Primero se reutilizan referencias técnicas aprobadas y precios comparables locales.
- Si ese resultado cubre la ficha, se omiten búsquedas y llamadas de completado adicionales.
- Una valoración firmada del mismo borrador sólo se reutiliza en el mismo día y con contexto compatible.
- Se mantienen cuotas, reservas, protección de correcciones humanas y `store=false`.
- El timeout es un máximo de espera, no un tiempo mínimo de ejecución.

La documentación oficial consultada el 11 de octubre de 2026 indica tarifas Standard
USD 0,10 por millón de tokens de entrada y USD 0,50 por millón de salida; entrada en
caché USD 0,01. Las herramientas de búsqueda tienen cargos adicionales.
Las pruebas locales simuladas no acreditan saldo ni tiempos reales del proveedor.

Fuentes oficiales:
- [GPT-6 Luna: capacidades y tarifas](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [Guía de los modelos actuales](https://developers.openai.com/api/docs/guides/latest-model)

## Configuración operativa

Establecer `OPENAI_MODEL=gpt-6-luna` en web y worker y reiniciar ambos.
Una variable de entorno existente tiene prioridad sobre el default del código.
La clave se conserva en producción. Los resultados anteriores no se recalculan
ni se alteran automáticamente. Verificar una ejecución real antes de afirmar
mejoras de latencia del proveedor o disponibilidad del modelo en la cuenta.

## Historial de la integración anterior

## Compatibilidad de los resultados de búsqueda

La prueba inicial de Astra identificó correctamente la serie y los renglones
técnicos de la placa, y la máquina de la fotografía general. También detectó que
el proveedor devolvía más de un elemento `web_search_call` por respuesta pese al
límite solicitado. El código anterior descartaba toda la investigación si el
conteo era distinto de uno. Esos ensayos se conservaron como fallidos.

La integración exige una respuesta completada y una búsqueda completada para
aceptar fuentes. Los intentos fallidos y las acciones de abrir o buscar dentro
de una página no autorizan por sí solos una URL como fuente recuperada. El límite
solicitado continúa siendo `max_tool_calls=1`, y todos los elementos recibidos se
contabilizan de forma conservadora. Los diagnósticos registran conteos por estado
y acción, sin consultas ni respuestas privadas completas.

Antes de continuar con otra etapa opcional, la investigación reserva espacio para
normalizar la evidencia ya encontrada. Así evita gastar toda la reserva buscando
y quedarse sin capacidad para trasladar los datos verificados a la ficha.
El cálculo de la siguiente búsqueda tiene en cuenta el mayor consumo observado
en las búsquedas previas de ese trabajo, sin aumentar su reserva ni la cuota diaria.

La comprobación real de v26 confirmó que las búsquedas se ejecutan y llegan a la
normalización. En la placa de prueba se conservaron ocho datos legibles, pero el
modelo quedó pendiente y las fuentes encontradas no identificaron esa misma
unidad. Esa prueba no acredita una ficha enriquecida por fuentes externas; su
objetivo de calidad completo permaneció fallido.

## Fidelidad de la fotografía

El análisis prioriza una copia decodificada del original y codificada en PNG sin
metadatos. Evita volver a comprimir el texto fino de una placa a partir de la vista
JPEG. Conserva orientación, encuadre y límites de tamaño; si ese camino no está
disponible utiliza la vista sanitizada. No reconstruye letras ni añade detalles.
Una lectura dudosa continúa pendiente de confirmar.
