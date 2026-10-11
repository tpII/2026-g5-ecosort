#!/usr/bin/env python3
"""Chequeo de formato de las entregas (docs/entregas/*.pdf) para el CI.

Corre `analizar_pdf.py` (la skill `formato-entregas` de https://github.com/tpII/ia-guidelines-taller, que no
se copia acá: el CI la trae con un checkout y se indica dónde está con --analizador o ANALIZAR_PDF) sobre cada
PDF y decide:

- **Falla** (sale con 1) lo que se mide con certeza: fuente permitida, cuerpo de 12 pt e interlineado 1,5.
- **Avisa** (queda en el informe, no falla) lo que puede dar falsos positivos con PDFs de Google Docs o Word:
  justificado, carátula, índices, bibliografía, epígrafes y lenguaje.

Uso:  check_entrega.py [pdf ...] [--base RAMA] [--analizador RUTA] [--salida DIR]
Qué PDFs mira, en este orden: los que se pasan como argumento; si no, con --base, los de docs/entregas/ que
cambian respecto de esa rama (son los de la entrega que se está promoviendo); si no, todos los de
docs/entregas/*.pdf. Si no hay ninguno, avisa y sale con 0.
"""
import argparse
import glob
import json
import os
import subprocess
import sys



def evaluar(d):
    """(errores, avisos) a partir del JSON de analizar_pdf.py. Pura: no toca archivos."""
    errores, avisos = [], []
    f, i, j, e, ep = d["fuentes"], d["interlineado"], d["justificado"], d["estructura"], d["epigrafes"]

    if not f["fuente_ok"]:
        errores.append(f"Fuente del cuerpo no permitida: {f['cuerpo']['familia']} "
                       f"(Arial, Times New Roman o Libertinus)")
    if not f["tamano_ok"]:
        errores.append(f"Tamaño del cuerpo {f['cuerpo']['size']} pt (se pide 12 pt)")
    if i["clase"] != "1,5":
        errores.append(f"Interlineado {i['clase']} (ratio {i['ratio']}); se pide 1,5. "
                       f"Páginas fuera: {i['paginas_fuera']}")

    if j["justificado"] != "sí":
        avisos.append(f"Justificado {j['justificado']}: páginas dudosas {j['paginas_dudosas']}")
    if not e["caratula"]["pag1_parece_caratula"]:
        avisos.append("La página 1 no parece una carátula")
    if not e["indice"]["presente"]:
        avisos.append("No se detectó el índice general")
    if ep["imagenes_por_pagina"] and not e["indice_figuras"]["presente"]:
        avisos.append("Hay figuras y no se detectó el índice de figuras")
    if ep["tablas_detectadas"] and not e["indice_tablas"]["presente"]:
        avisos.append("Hay tablas y no se detectó el índice de tablas")
    if not e["bibliografia"]["presente"]:
        avisos.append("No se detectó la bibliografía / referencias")
    if ep["imagenes_grandes_sin_epigrafe"]:
        pags = sorted({x["pag"] for x in ep["imagenes_grandes_sin_epigrafe"]})
        avisos.append(f"Imágenes grandes sin epígrafe «Figura N» cerca (páginas {pags}); pueden ser logos")
    if d["lenguaje"]:
        avisos.append(f"{len(d['lenguaje'])} candidatos de primera persona o voseo (leer el contexto en el informe)")
    return errores, avisos


def pdfs_cambiados(base, carpeta="docs/entregas"):
    """PDFs de `carpeta` nuevos, modificados o renombrados en HEAD respecto de la rama `base`."""
    r = subprocess.run(["git", "diff", "--name-only", "--diff-filter=AMR", base, "HEAD", "--", carpeta],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git diff contra {base} falló:\n{r.stderr}")
    return sorted(x for x in r.stdout.splitlines() if x.lower().endswith(".pdf"))


def correr(analizador, pdf, extra=()):
    r = subprocess.run([sys.executable, analizador, pdf, *extra], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"analizar_pdf.py falló sobre {pdf}:\n{r.stderr or r.stdout}")
    return r.stdout


def chequear(analizador, pdf, salida):
    datos = json.loads(correr(analizador, pdf, ["--json"]))
    informe = correr(analizador, pdf)
    errores, avisos = evaluar(datos)

    partes = [f"## `{os.path.basename(pdf)}`: " + ("❌ no cumple el formato" if errores else "✅ cumple lo mecánico")]
    if errores:
        partes += ["", "**Falla el CI por:**"] + [f"- ❌ {x}" for x in errores]
    if avisos:
        partes += ["", "**A revisar (no falla el CI):**"] + [f"- ⚠️ {x}" for x in avisos]
    partes += ["", "<details><summary>Informe completo</summary>", "", informe, "", "</details>", ""]
    resumen = "\n".join(partes)

    os.makedirs(salida, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf))[0]
    with open(os.path.join(salida, base + "_chequeo.md"), "w", encoding="utf-8") as fh:
        fh.write(resumen)
    return errores, resumen


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="*")
    ap.add_argument("--analizador", default=os.environ.get("ANALIZAR_PDF"),
                    help="ruta a skills/formato-entregas/scripts/analizar_pdf.py del repo de la cátedra")
    ap.add_argument("--base", help="rama contra la que se compara (por ejemplo origin/entrega_2): "
                    "solo se chequean los PDFs de docs/entregas/ que cambian respecto de ella")
    ap.add_argument("--salida", default="entregas-chequeo")
    args = ap.parse_args()

    if args.pdf:
        pdfs = args.pdf
    elif args.base:
        pdfs = pdfs_cambiados(args.base)
    else:
        pdfs = sorted(glob.glob("docs/entregas/*.pdf"))
    if not pdfs:
        print("No hay PDFs para chequear en docs/entregas/" + (f" respecto de {args.base}" if args.base else "")
              + ": nada que chequear.")
        return 0

    if not args.analizador or not os.path.isfile(args.analizador):
        sys.exit("Falta analizar_pdf.py: clonar https://github.com/tpII/ia-guidelines-taller y pasar "
                 "--analizador <repo>/skills/formato-entregas/scripts/analizar_pdf.py (o ANALIZAR_PDF).")

    fallo, todo = False, []
    for pdf in pdfs:
        errores, resumen = chequear(args.analizador, pdf, args.salida)
        print(resumen)
        todo.append(resumen)
        fallo = fallo or bool(errores)

    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as fh:
            fh.write("# Formato de las entregas\n\n" + "\n".join(todo))
    return 1 if fallo else 0


if __name__ == "__main__":
    sys.exit(main())
