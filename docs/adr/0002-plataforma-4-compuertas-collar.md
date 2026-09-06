# ADR 0002 — Mecanismo físico: plataforma de 4 compuertas

**Estado:** Aceptado.

## Contexto

El catálogo fija 4 clases y confirmó que se pueden usar 4 servos SG90 (uno
por clase). Se evaluaron tres mecanismos antes de llegar a este:

1. Torreta rotativa de un solo servo.
2. Rampa con aletas distribuidas a lo largo del trayecto.
3. Rampa única con una estación final de 3 aletas + caída por defecto a
   orgánico (sin servo propio para orgánico).

Diagrama completo, con las 3 iteraciones descartadas conservadas como
referencia histórica: ver el esquema físico enlazado desde
`plan-arquitectura-ecosort.md`.

## Decisión

Plataforma fija con 4 compuertas — una por clase, las 4 con su propio
servo. Las 4 arrancan **cerradas**; la
correspondiente a la clase detectada (o a baja confianza) se abre y deja
caer el residuo a su contenedor.

Las alternativas descartadas dependían de que el residuo completara un
recorrido por gravedad predecible o de acertar el timing de un objeto en
movimiento — riesgos evitables una vez que se nos confirmó que 4
servos eran una opción válida (inicialmente se había asumido un límite de
3).

## Consecuencias

- Todas las clases, incluida orgánico, recorren exactamente el mismo
  trayecto — no hay una ruta "más larga" para ninguna clase en particular.
- Baja confianza y clase orgánico comparten el mismo contenedor físico
  (ambas abren la compuerta de orgánico) — ese bin va a tener peor pureza
  que los otros 3 por construcción, no por error del modelo. Documentar
  esto explícitamente en `docs/validacion.md`.
- Pendiente de validar con residuos reales en la etapa final del proyecto.
