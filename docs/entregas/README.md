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

`entrega_*` no se toca a mano: sin pushes directos, solo esta promoción (se configura en Settings → Rules).

**Si el chequeo falla**, se corrige el documento, se exporta el PDF de nuevo y se sube a `main` **con el mismo nombre**
(reemplaza al anterior). El PR de promoción que ya está abierto se actualiza solo y el CI vuelve a correr. Si se sube
con otro nombre, el PDF viejo sigue en la carpeta y sigue fallando: habría que borrarlo. Corregir solo el Google Doc
no alcanza: el CI mide el PDF commiteado.

## Cómo se chequea

El job `entrega` del CI corre
[`check_entrega.py`](../../.github/scripts/formato-entregas/check_entrega.py). Usa la
skill `formato-entregas` de la cátedra ([ia-guidelines-taller](https://github.com/tpII/ia-guidelines-taller)), que el
CI trae con un checkout del repo (fijado a un commit, en `ci.yml`) y no está copiada acá. Mide el **PDF** (no el
`.docx` ni el Google Doc), así que hay que exportarlo y commitearlo.

| Resultado | Qué lo causa |
|---|---|
| ❌ **Falla el CI** | Fuente que no es Arial, Times New Roman o Libertinus; cuerpo distinto de 12 pt; interlineado que no es 1,5 |
| ⚠️ **Aviso** (no falla) | Justificado parcial, sin carátula, sin índice, sin bibliografía, figuras sin epígrafe, candidatos de primera persona o voseo |

Los avisos pueden ser falsos positivos (el detector de índice y de epígrafes tiene límites con PDFs de Google Docs),
así que hay que leerlos. El informe completo queda en el **resumen del job** y como artefacto `chequeo-formato`.
Lo que la skill no puede medir (registro técnico, formato de la bibliografía, ortografía, siglas sin definir) es
revisión humana, según su [rúbrica](https://github.com/tpII/ia-guidelines-taller/blob/main/skills/formato-entregas/references/rubrica.md).

## Probarlo antes de subirlo

```bash
sudo apt install poppler-utils                       # una vez (Debian/Ubuntu)
git clone --depth 1 https://github.com/tpII/ia-guidelines-taller.git /tmp/guias
python3 .github/scripts/formato-entregas/check_entrega.py docs/entregas/informe.pdf \
  --analizador /tmp/guias/skills/formato-entregas/scripts/analizar_pdf.py
```

Sale con 1 si algo de la tabla ❌ no cumple. Sin argumentos revisa todo `docs/entregas/*.pdf`; con
`--base origin/entrega_2`, solo los que cambian respecto de esa rama (lo que hace el CI).

## Nota

`docs/Plan de Proyecto-G5.pdf` (la primera entrega) está fuera de esta carpeta a propósito: no se mide y no
pasaría el chequeo (13 pt e interlineado simple).
