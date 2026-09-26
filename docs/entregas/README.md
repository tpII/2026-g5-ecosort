# Entregas

Acá van los PDF de cada entrega (informes, planes). Es lo único que chequea el CI de formato.

## Cómo se chequea

Cuando se abre un PR **hacia** una rama `entrega_*` (por ejemplo `entrega_2`, la rama donde se junta una entrega),
el job `entrega` del CI corre
[`check_entrega.py`](../../.github/scripts/formato-entregas/check_entrega.py) sobre `docs/entregas/*.pdf`. Usa la
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

Sale con 1 si algo de la tabla ❌ no cumple. Sin argumentos revisa todo `docs/entregas/*.pdf`.

## Nota

`docs/Plan de Proyecto-G5.pdf` (la primera entrega) está fuera de esta carpeta a propósito: no se mide y no
pasaría el chequeo (13 pt e interlineado simple).
