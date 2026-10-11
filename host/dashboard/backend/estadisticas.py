"""Agregaciones de solo lectura sobre la tabla `eventos`, para `/api/estadisticas/*` (backend.py).

Funciones puras sobre listas de dicts ya leídas de SQLite: no abren la base ni conocen HTTP, así
que se prueban solas, sin Docker ni servidor (test_estadisticas.py). Son la cantidad y los tiempos
que se pidió poder graficar (por clase, por día, por hora del día, latencia) — la observabilidad de
infraestructura (Prometheus/Grafana, ADR 0004/0005) es un objetivo aparte, para después.

Se agrupa siempre en ZONA_HORARIA (`ECOSORT_ZONA_HORARIA`), nunca en la que tenga configurada el
contenedor donde corre esto (por defecto UTC en la imagen base, `python:3.12-slim`, sin `TZ`
seteada). `ts_recepcion` es un instante correcto (reloj del host al recibir, confiable — ver
docs/contrato-mqtt.md), pero el *offset* con el que quedó guardado es el que tuviera el sistema
operativo en ese momento, no necesariamente el de Argentina. Sin esta conversión, un "patrón
horario" quedaría corrido esas horas de diferencia (hoy, 3 horas) — y un evento cerca de la
medianoche podría contarse en el día calendario equivocado.
"""

import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_HORARIA = ZoneInfo(os.getenv("ECOSORT_ZONA_HORARIA", "America/Argentina/Buenos_Aires"))

AGRUPAR_VALIDOS = ("dia", "hora", "hora_del_dia")


def _local(ts_recepcion):
    """ts_recepcion (ISO 8601 con su propio offset) a un datetime en ZONA_HORARIA."""
    return datetime.fromisoformat(ts_recepcion).astimezone(ZONA_HORARIA)


def parsear_fecha(texto, fin_del_dia=False):
    """'2026-09-01' o una fecha-hora ISO -> datetime en ZONA_HORARIA. None si texto es None o
    vacío. Con fin_del_dia=True, una fecha sin hora se toma como el final de ese día (23:59:59.999),
    para que un 'hasta' de solo fecha incluya el día completo."""
    if not texto:
        return None
    t = datetime.fromisoformat(texto)
    if t.tzinfo is None:
        if fin_del_dia and len(texto) <= 10:  # solo fecha, sin hora ('2026-09-01')
            t = t.replace(hour=23, minute=59, second=59, microsecond=999999)
        t = t.replace(tzinfo=ZONA_HORARIA)
    return t.astimezone(ZONA_HORARIA)


def filtrar(filas, desde=None, hasta=None, dispositivo=None):
    """desde/hasta: como los recibe la API (texto o None). Ambos límites son inclusivos."""
    d0, d1 = parsear_fecha(desde), parsear_fecha(hasta, fin_del_dia=True)
    salida = []
    for f in filas:
        if dispositivo is not None and f["dispositivo_id"] != dispositivo:
            continue
        t = _local(f["ts_recepcion"])
        if d0 is not None and t < d0:
            continue
        if d1 is not None and t > d1:
            continue
        salida.append(f)
    return salida


def _agrupar_por(filas, campo):
    grupos = defaultdict(list)
    for f in filas:
        grupos[f[campo]].append(f)
    return grupos


def _percentiles(valores):
    if not valores:
        return None
    valores = sorted(valores)
    n = len(valores)

    def p(q):
        return valores[min(n - 1, int(q * n))]

    return {"n": n, "promedio": round(statistics.fmean(valores), 1), "p50": p(0.50), "p95": p(0.95)}


def resumen(filas):
    """Total, por clase (cantidad y confianza promedio) y latencia. Para `organico` además separa
    lo genuino de lo `incierto` (ADR 0002: baja confianza o cuadros inconsistentes que se fuerzan
    a esta clase) — es la pureza real del contenedor, no solo cuánto cayó ahí."""
    por_clase = {}
    for clase, grupo in _agrupar_por(filas, "clase").items():
        confianzas = [f["confianza"] for f in grupo if f.get("confianza") is not None]
        entrada = {
            "total": len(grupo),
            "confianza_promedio": round(statistics.fmean(confianzas), 4) if confianzas else None,
        }
        if clase == "organico":
            motivos = Counter(f["motivo"] for f in grupo if f.get("motivo"))
            entrada["incierto"] = dict(motivos)
            entrada["genuino"] = entrada["total"] - sum(motivos.values())
        por_clase[clase] = entrada
    latencias = [f["latencia_ms"] for f in filas if f.get("latencia_ms") is not None]
    return {"total": len(filas), "por_clase": por_clase, "latencia_ms": _percentiles(latencias)}


def serie(filas, agrupar="dia"):
    """Cantidad de eventos por clave, para un gráfico de barras o líneas.
    'dia'          un punto por fecha calendario (AAAA-MM-DD), en ZONA_HORARIA: una serie temporal.
    'hora'         un punto por hora calendario (AAAA-MM-DDTHH), en ZONA_HORARIA: más fino.
    'hora_del_dia' un punto por hora del día (0 a 23), sin fecha: el patrón de uso a lo largo del
                   día (para saber, por ejemplo, a qué hora se tira más), siempre con las 24 horas
                   presentes aunque alguna tenga 0."""
    if agrupar not in AGRUPAR_VALIDOS:
        raise ValueError(f"agrupar tiene que ser uno de {AGRUPAR_VALIDOS}, no {agrupar!r}")
    conteo = Counter()
    for f in filas:
        t = _local(f["ts_recepcion"])
        if agrupar == "dia":
            clave = t.date().isoformat()
        elif agrupar == "hora":
            clave = t.strftime("%Y-%m-%dT%H:00")
        else:
            clave = t.hour
        conteo[clave] += 1
    if agrupar == "hora_del_dia":
        puntos = [{"clave": h, "total": conteo.get(h, 0)} for h in range(24)]
    else:
        puntos = [{"clave": k, "total": v} for k, v in sorted(conteo.items())]
    return {"agrupar": agrupar, "puntos": puntos}


def dispositivos(filas):
    """Un resumen por dispositivo (forward-compat con N Pis, ADR 0003 — hoy hay una sola)."""
    salida = {}
    for disp, grupo in _agrupar_por(filas, "dispositivo_id").items():
        # se ordena por el instante real (_local), no por el string: dos ts_recepcion con distinto
        # offset (por ejemplo si el reloj del contenedor cambia de huso) no ordenan bien como texto
        marcas = sorted((f["ts_recepcion"] for f in grupo), key=_local)
        salida[disp] = {"total": len(grupo), "primer_evento": marcas[0], "ultimo_evento": marcas[-1]}
    return salida
