# Recuperación prudente de sufijos de modelo — 2026-09-25

## Caso que cubre

Una placa puede dejar visible un código parcial, mientras que una fuente pública
relaciona la misma serie con un código más largo. Por ejemplo, una lectura de
placa puede terminar antes de un sufijo. Esa fuente externa es una señal para
revisar, no una corrección automática de la placa.

## Contrato aplicado

`research.py` acepta un candidato sólo si se cumplen todas estas condiciones:

1. La marca, el modelo de placa y la serie ya son identificadores claros o
   declarados.
2. El modelo de placa es un código alfanumérico de cuatro o más caracteres y
   la fuente cita literalmente un código que lo prolonga, sin cambiar su
   prefijo.
3. El mismo fragmento cita la serie completa; marca y candidato aparecen en
   el fragmento o la marca aparece en el título recuperado de esa misma URL.
4. La URL pasa la validación pública normal.

El candidato queda en `research.hypotheses` con
`relation: "serial_model_extension"`. Con una sola fuente tiene
`confidence: "lead"`. Sólo pasa a `"supported"` cuando una URL distinta de
fabricante o catálogo técnico registrado cita de forma literal la misma marca
y candidato. Ambos casos siguen siendo una hipótesis firmada para comparar con
la placa.

No se cambia `research.identity.model`, `data.model` ni la procedencia de la
lectura. Las especificaciones, periodos de fabricación, año de la unidad y
precio asociados al candidato se descartan. Por ello una coincidencia de
vendedor con la serie no puede rellenar capacidad, año ni valor.

## Búsqueda y degradación

La detección se realiza dentro del resultado de la etapa de serie ya existente.
Si aparece una señal válida, los pasos normales posteriores de fabricante y
catálogo incluyen el candidato como consulta de revisión. No se añade una
llamada de IA ni se consulta una API privada. Si esos pasos no devuelven una
corroboración válida, queda sólo el `lead`; si la extracción o búsqueda falla,
la lectura original se conserva y no se crea un candidato.

La valoración continúa exigiendo marca, modelo y condición de la identidad
confirmada, además de al menos dos anuncios individuales verificables. Nunca
usa una hipótesis para buscar comparables ni propone importe cuando faltan
precios públicos legibles.

## Verificación local

`portal/tests/test_research_serial_model_extensions.py` reproduce una serie
con lectura parcial y un candidato de sufijo. Comprueba que las tres etapas ya
existentes no hacen solicitudes adicionales, que una fuente de fabricante y
otra de catálogo sólo dan soporte a la hipótesis, y que ningún campo técnico,
año o precio entra al resultado. La segunda prueba confirma que una única
publicación queda como `lead` y nunca reemplaza el código de placa.
