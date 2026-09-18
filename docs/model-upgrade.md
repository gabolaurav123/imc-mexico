# Modelo de análisis y búsqueda

La configuración predeterminada usa **GPT-6 Astra** (`gpt-6-astra`) mediante
Responses. Sustituye el valor inicial `gpt-4.1-mini`. Las instalaciones existentes
deben actualizar su variable `OPENAI_MODEL` y desplegar la aplicación para que web
y worker carguen el mismo valor. La clave de producción permanece en el servidor.

## Perfil de ejecución

- Razonamiento `low` explícito en lectura de fotos, descripción, búsqueda,
  normalización de fuentes y valoración.
- 3.500 tokens adicionales de salida y de reserva por llamada; el espacio de
  salida incluye tanto razonamiento como datos de la ficha.
- Timeout mínimo de 120 segundos por llamada. La vigencia del trabajo contempla
  todas las etapas y el número de fotografías.
- Las mismas etapas, límites diarios, documentos permitidos y fuentes verificables.
  Una llamada posterior sólo comienza si dispone de reserva suficiente.
- Cada trabajo conserva su modelo. Los resultados ya generados no se recalculan
  al desplegar; el propietario puede solicitar un nuevo análisis desde su ficha.
- No hay descenso automático a un modelo mini ante un fallo de acceso o proveedor.

La ficha conserva la edición y protección de correcciones humanas, la separación
entre lectura de placa y referencia de catálogo, y las validaciones de identidad,
precio y procedencia. Un modelo mejor no convierte la sede del fabricante en país
de fabricación ni permite saber dónde se encuentra hoy una máquina por su serie.

## Coste y documentación

El consumo de API se factura por separado del alojamiento. Las tarifas Standard
consultadas para Astra son USD 10 por millón de tokens de entrada y USD 50 por
millón de salida, más herramientas y las reglas de caché aplicables. Los tokens
de razonamiento forman parte de la salida. La reserva interna es un límite de
capacidad, no un precio por ficha; el coste depende de fotos, fuentes y respuestas.

Fuentes oficiales consultadas para esta implementación:

- [GPT-6 Astra: capacidades y tarifas](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Parámetros de migración](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart)
- [Razonamiento y presupuesto de salida](https://developers.openai.com/api/docs/guides/reasoning)

La validación de despliegue debe registrar el modelo del trabajo y el devuelto por
la lectura real, la extracción de una placa, una fotografía general, los campos
guardados, la ficha web/PDF y la conservación de ediciones. Los tests simulados
comprueban compatibilidad y contabilidad; no demuestran calidad visual por sí solos.
