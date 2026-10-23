# Entregas

Acá van los PDF de cada entrega (informes, planes). Es lo único que chequea el CI de formato.

## Flujo

1. Los PDF entran a `main` por PRs normales, como cualquier otro cambio. Ahí no se chequea el formato, así que
   corregir un informe no frena a nadie que esté con una feature.
2. Cuando la entrega está lista, se abre un PR **de `main` hacia `entrega_N`** (por ejemplo `entrega_2`, que sale
   de la entrega anterior). Es el único origen válido: el CI rechaza cualquier otro. Se mergea con *merge commit*
   (no squash), para que `entrega_N` siga alineada con `main`.
3. Sobre ese PR corre el chequeo de formato de los PDF de `docs/entregas/` **que cambian respecto de `entrega_N`**,
   es decir los de esta entrega: los de las anteriores no se vuelven a medir.
4. Al mergear, se crea el tag `entrega-N` sobre `entrega_N`, que queda como lo que se entregó.

`entrega_*` no se toca a mano: sin pushes directos, solo esta promoción (se configura en Settings → Rules —
**falta confirmar que el ruleset ya esté armado en GitHub**, ver `README.md` raíz, Pendiente).

**Si el chequeo falla**, se corrige el documento, se exporta el PDF de nuevo y se sube a `main` **con el mismo nombre**
(reemplaza al anterior). El PR de promoción que ya está abierto se actualiza solo y el CI vuelve a correr. Si se sube
con otro nombre, el PDF viejo sigue en la carpeta y sigue fallando: habría que borrarlo. Corregir solo el Google Doc
no alcanza: el CI mide el PDF commiteado.

## Cómo se chequea

El job `entrega` del CI corre [`prolijito`](https://github.com/festradax07/prolijito) (herramienta propia del
equipo, evolucionada de un chequeador que armamos para este mismo repo) con el perfil
[`.github/prolijito/ecosort-entrega.yaml`](../../.github/prolijito/ecosort-entrega.yaml), que por ahora hereda
sin cambios de `unlp-tp2`, el perfil que trae prolijito para esta cátedra. Mide el **PDF** (no el `.docx` ni el
Google Doc), así que hay que exportarlo y commitearlo.

| Resultado | Qué lo causa |
|---|---|
| ❌ **Falla el CI** | Fuente que no es Arial, Times New Roman o Libertinus; cuerpo distinto de 12 pt; interlineado que no es 1,5; justificado; sin carátula, índice o bibliografía; índice con páginas que no coinciden con el documento; epígrafes mal puestos o ausentes; índice de figuras/tablas ausente si hay figuras o tablas |
| ❓ **A revisar** (no falla) | Candidatos de primera persona o voseo, otras familias tipográficas minoritarias |

prolijito deja el reporte completo en el **resumen del job** (anotaciones por línea) y como artefacto
`chequeo-formato`. Lo que no puede medir (registro técnico, ortografía, siglas sin definir) es revisión humana.

**`docs/entregas/entrega-2.pdf` no pasa este chequeo hoy** (25 errores: sin índice de figuras ni de tablas, el
índice general quedó con páginas desactualizadas respecto del documento, dos epígrafes de tabla arriba en vez de
abajo, y 9 tablas sin epígrafe) — no bloquea nada mientras esté en `main`, pero hay que corregirlo antes de
promoverlo a una rama `entrega_*`.

## Probarlo antes de subirlo

```bash
docker run --rm -v "$PWD:/work" -w /work -u "$(id -u):$(id -g)" \
  ghcr.io/festradax07/prolijito:0.3.1 check docs/entregas/informe.pdf \
  --profile ecosort-entrega --profiles-dir .github/prolijito
```

Sale con 1 si hay errores. Ver más formas de instalarlo (binario, pip) en el
[README de prolijito](https://github.com/festradax07/prolijito#instalaci%C3%B3n).

## Nota

`docs/Plan de Proyecto-G5.pdf` (la primera entrega) está fuera de esta carpeta a propósito: no se mide y no
pasaría el chequeo (13 pt e interlineado simple).
