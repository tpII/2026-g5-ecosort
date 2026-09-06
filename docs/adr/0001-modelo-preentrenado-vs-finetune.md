# ADR 0001 — Modelo: preentrenado vs. fine-tuning vs. entrenamiento desde cero

**Estado:** Propuesto — pendiente confirmar herramienta drag-and-drop exacta con el docente.

## Contexto

Necesitamos un clasificador de imágenes de 4 clases (plástico, papel, vidrio,
orgánico) que corra en una Raspberry Pi 3 vía TFLite, con un cronograma de
entrega en dos tramos (octubre / noviembre) y sin acceso a GPU de
entrenamiento dedicada.

## Decisión

Fine-tuning sobre un modelo preentrenado, usando una herramienta
drag-and-drop (Teachable Machine o similar — a confirmar con el docente) que
exporta directo a TFLite int8.

Se descarta entrenar desde cero por: tiempo disponible, tamaño del dataset
propio que el equipo puede armar, y capacidad de cómputo disponible (sin
GPU). Se descarta usar el preentrenado sin ajuste por: las clases del
dataset base no coinciden 1:1 con las 4 categorías del proyecto, y el
fine-tuning con una herramienta drag-and-drop tiene un costo marginal bajo
sobre esa alternativa.

## Consecuencias

- Permite iterar el modelo probándolo con la cámara de una notebook, en
  paralelo y desde el día 1, sin esperar a que el hardware esté armado (ver
  estrategia de walking skeleton en `plan-de-proyecto.pdf`).
- El export a TFLite int8 es el mismo formato que corre en la Pi — no hay
  paso de conversión adicional que pueda introducir sorpresas de último
  momento.
- Pendiente: probar los datasets (TACO, TrashNet, fotos propias, o combinación).
