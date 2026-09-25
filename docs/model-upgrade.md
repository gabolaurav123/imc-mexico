# Modelo de análisis y búsqueda

La política predeterminada vigente, restablecida el 25 de septiembre de 2026 según
la elección expresa del propietario, usa **GPT-5.6 Terra** para la lectura visual y
**GPT-5.6 Luna** (`OPENAI_MODEL=gpt-5.6-luna`) para investigación, normalización y
texto mediante Responses. Es una política por etapa dentro de los dos modelos
autorizados por el propietario: una sola llamada por foto, sin reintento con
otro modelo. Se registra `requested_model` y el modelo devuelto por el proveedor
para cada fotografía. Los trabajos anteriores conservan su modelo encolado.
El propietario retiró Astra por coste y permanece bloqueado.

## Perfil y control de consumo

- Razonamiento `low` en fotos generales, descripción, búsqueda, normalización y valoración;
  `medium` para placas con Terra, dentro de la misma llamada visual.
- 3.500 tokens de margen por llamada para razonamiento/salida y timeout mínimo de 120 segundos.
- Se conservan las cuotas diarias y las reservas acotadas. La reserva no es una tarifa.
- Astra está bloqueado antes de encolar y antes de llamar al proveedor, incluidos trabajos antiguos.
- La clave permanece en producción. Los resultados anteriores no se recalculan automáticamente.
- Las correcciones humanas y la validación de las fuentes siguen vigentes.

Las tarifas Standard consultadas de Luna son USD 0,20 por millón de tokens de
entrada y USD 1,20 por millón de salida. Herramientas, caché y contexto largo tienen
reglas adicionales. Terra tiene una tarifa Standard mayor: USD 2 por millón de
tokens de entrada y USD 12 por millón de salida, según la documentación consultada
el 25 de septiembre de 2026. Su uso se limita a la lectura visual.
Las pruebas locales usan respuestas simuladas y no acreditan calidad visual real
ni saldo disponible en la cuenta del proveedor.

Fuentes oficiales:
- [GPT-5.6 Luna: capacidades y tarifas](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [GPT-5.6 Terra: alternativa compatible](https://developers.openai.com/api/docs/models/gpt-5.6-terra)

## Configuración operativa

Establecer `OPENAI_MODEL=gpt-5.6-luna` en web y worker y reiniciar ambos.
Cambiar sólo el default del código no reemplaza una variable de entorno existente.
Los trabajos ya encolados conservan `model` y `vision_model`; no se recalculan
resultados históricos ni se introduce una segunda llamada para cambiar de modelo.

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
