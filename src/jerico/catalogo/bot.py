"""Comandos de Telegram para el catálogo de precios y cotizaciones (Spec 006).

Permite:
1. Al comercial: ver planes disponibles (/catalogo) y cotizar determinísticamente (/cotizar).
2. Al CTO: ver costos/márgenes internos (/catalogo), activar versión vigente (/catalogo_activar),
   actualizar precios generando nuevas versiones semver (/catalogo_actualizar)
   y verificar concordancia con el modelo financiero (/catalogo_verificar).
"""

import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any

from jerico.catalogo.cotizar import (
    PlanNoEncontradoError,
    cotizar_plan,
)
from jerico.catalogo.modelo import CatalogoPrecios
from jerico.catalogo.repositorio import (
    CatalogoSinVersionVigenteError,
    RepositorioCatalogo,
    VersionCatalogoNoEncontradaError,
)
from jerico.catalogo.verificador import verificar_catalogo
from jerico.catalogo.vista import (
    VistaComercial,
    VistaCTO,
    obtener_vista,
)
from jerico.crm.bot import CrmBot
from jerico.crm.model import Outgoing, Role, User
from jerico.schemas import Cotizacion


def _formatear_pesos(valor: int | Decimal) -> str:
    """Formatea importes enteros en pesos colombianos con separador de miles."""
    v_int = int(valor)
    return f"${v_int:,.0f}".replace(",", ".") + " COP"


def _obtener_catalogo_activo(repo: RepositorioCatalogo) -> tuple[CatalogoPrecios, bool]:
    """Obtiene el catálogo vigente o el borrador disponible si aún no hay vigente."""
    try:
        return repo.cargar_vigente(), True
    except CatalogoSinVersionVigenteError:
        # Fallback a la primera versión semver encontrada para consulta informativa
        archivos = sorted(repo.directorio.glob("*.yaml"))
        for arch in archivos:
            v_nombre = arch.stem
            try:
                return repo.cargar_version(v_nombre), False
            except (VersionCatalogoNoEncontradaError, ValueError):
                pass
        raise CatalogoSinVersionVigenteError(
            "catálogo sin versión vigente ni borradores válidos"
        ) from None


def formatear_vista_comercial(vista: VistaComercial, version: str, estado: str) -> str:
    """Construye el texto de Telegram para el comercial (R7, R12)."""
    lineas: list[str] = ["💼 *CATÁLOGO DE SERVICIOS KAIZEN AI*"]
    if estado != "vigente":
        lineas.append(f"⚠️ *BORRADOR (v{version}) — no cotizar hasta aprobación del CTO*\n")
    else:
        lineas.append(f"✅ *Versión vigente:* v{version}\n")

    lineas.append("*Planes disponibles:*")
    for p in vista.planes:
        m_est = p.mensualidad
        lineas.append(
            f"🔹 *{p.nombre}* (`{p.id}`)\n"
            f"   • Implementación: {_formatear_pesos(p.precio_propuesta)}\n"
            f"   • Mensualidad estimada (10 %): {_formatear_pesos(m_est)}/mes"
        )

    lineas.append(
        "\n📝 *Para cotizar:* `/cotizar <plan> [meses]`\n   _Ejemplo:_ `/cotizar estandar 12`"
    )
    return "\n".join(lineas)


def formatear_vista_cto(vista: VistaCTO, version: str, estado: str) -> str:
    """Construye el texto de Telegram para el CTO con costos y márgenes (R8, R13)."""
    lineas: list[str] = [f"🛠️ *PANEL DE PRECIOS CTO — KAIZEN AI* (v{version})"]
    if estado != "vigente":
        lineas.append("⚠️ *ESTADO: BORRADOR — Requiere activación oficial*\n")
    else:
        lineas.append("✅ *ESTADO: VIGENTE OFICIAL*\n")

    if vista.interno:
        c_dir_str = (
            _formatear_pesos(vista.interno.costo_directo_por_implementacion)
            if vista.interno.costo_directo_por_implementacion is not None
            else "N/A"
        )
        lineas.append(
            f"📊 *Estructura interna base:*\n"
            f"   • Costo directo por implementación: {c_dir_str}\n"
            f"   • Capacidad anual: "
            f"{vista.interno.capacidad_implementaciones_anio} implementaciones/año\n"
        )
    else:
        lineas.append("📊 *Estructura interna base:* No definida en esta versión\n")

    lineas.append("*Detalle por Plan:*")
    for p in vista.planes:
        m_real_str = f"{p.interno.margen_real_pct:.1f} %" if p.interno is not None else "N/A"
        lineas.append(
            f"🔹 *{p.nombre}* (`{p.id}`)\n"
            f"   • Precio propuesta (real): {_formatear_pesos(p.precio_propuesta)}\n"
            f"   • Precio fórmula (P&L): {_formatear_pesos(p.precio_formula)}\n"
            f"   • Margen objetivo: {p.margen_objetivo_pct:.1f} %\n"
            f"   • Margen real: {m_real_str}"
        )

    if vista.advertencias:
        lineas.append("\n⚠️ *Advertencias financieras:*")
        for adv in vista.advertencias:
            lineas.append(f"   • {adv}")

    lineas.append(
        "\n⚙️ *Comandos de administración:*\n"
        f"   • `/catalogo_activar {version}` — Fijar versión como vigente (R3)\n"
        "   • `/catalogo_actualizar <version> <plan> <precio>` — Crear versión semver\n"
        f"   • `/catalogo_verificar {version}` — Auditar contra Excel (R6)"
    )
    return "\n".join(lineas)


def formatear_cotizacion_telegram(cot: Cotizacion, estado_catalogo: str, version: str) -> str:
    """Formatea una cotización formal bajo el contrato Cotizacion (R4, R14)."""
    lineas: list[str] = ["📄 *COTIZACIÓN DE SERVICIOS KAIZEN AI*"]
    if estado_catalogo != "vigente":
        lineas.append(f"⚠️ *BORRADOR — Catálogo v{version} (no enviar a cliente final)*\n")
    else:
        lineas.append(f"✅ *Catálogo oficial:* v{version}\n")

    lineas.append(f"*Moneda:* {cot.currency} (precios sin IVA)")
    lineas.append("*Desglose:*")
    for linea in cot.lines:
        cant_str = f" x{linea.quantity}" if linea.quantity > 1 else ""
        subtotal_linea = linea.quantity * linea.unit_price
        subt = _formatear_pesos(subtotal_linea)
        lineas.append(f"   • {linea.description}{cant_str}: {subt}")

    lineas.append(f"\n💰 *TOTAL IMPLEMENTACIÓN + SOPORTE:* {_formatear_pesos(cot.total)}")
    lineas.append("_Nota: IVA del 19 % aplicable al momento de facturación._")
    return "\n".join(lineas)


def catalogo_command(
    conn: sqlite3.Connection,
    user: User,
    text: str,
    now: datetime,
    repo: RepositorioCatalogo | None = None,
) -> list[Outgoing]:
    """Comando /catalogo para consultar planes según el rol del usuario (R7, R8)."""
    r = repo or RepositorioCatalogo()
    try:
        catalogo, _ = _obtener_catalogo_activo(r)
    except CatalogoSinVersionVigenteError:
        return [
            Outgoing(
                user.telegram_id,
                "⚠️ *Catálogo sin versión vigente*: no hay precios oficiales activos. "
                "El CTO debe configurar y activar una versión con `/catalogo_activar`.",
            )
        ]

    rol_str = "cto" if user.role == Role.CTO else "comercial"
    vista = obtener_vista(catalogo, rol=rol_str)

    if isinstance(vista, VistaCTO):
        msg = formatear_vista_cto(vista, catalogo.version, catalogo.estado)
    else:
        msg = formatear_vista_comercial(vista, catalogo.version, catalogo.estado)

    return [Outgoing(user.telegram_id, msg)]


def cotizar_command(
    conn: sqlite3.Connection,
    user: User,
    text: str,
    now: datetime,
    repo: RepositorioCatalogo | None = None,
) -> list[Outgoing]:
    """Comando /cotizar [plan] [meses] determinista bajo contrato Cotizacion (R4, R11, R14)."""
    r = repo or RepositorioCatalogo()
    try:
        catalogo, _ = _obtener_catalogo_activo(r)
    except CatalogoSinVersionVigenteError:
        return [
            Outgoing(
                user.telegram_id,
                "⚠️ *No es posible cotizar*: el catálogo no tiene una versión vigente activa. "
                "Pídele al CTO que active una versión.",
            )
        ]

    partes = text.strip().split()
    # Si solo invocó /cotizar sin argumentos, devuelve el listado de planes
    if len(partes) < 2:
        vista_com = obtener_vista(catalogo, rol="comercial")
        if isinstance(vista_com, VistaComercial):
            msg = formatear_vista_comercial(vista_com, catalogo.version, catalogo.estado)
        else:
            msg = "Error al obtener vista comercial."
        return [Outgoing(user.telegram_id, msg)]

    plan_id = partes[1].lower()
    meses = 12
    if len(partes) >= 3:
        try:
            meses = int(partes[2])
            if meses <= 0:
                raise ValueError()
        except ValueError:
            return [
                Outgoing(
                    user.telegram_id,
                    "⚠️ La cantidad de meses de mensualidad debe ser un número entero positivo "
                    "(ejemplo: `/cotizar estandar 12`).",
                )
            ]

    try:
        cot = cotizar_plan(catalogo, plan_id, meses_mensualidad=meses)
    except PlanNoEncontradoError as err:
        validos = ", ".join(f"`{p}`" for p in err.planes_validos)
        return [
            Outgoing(
                user.telegram_id,
                f"⚠️ El plan `{plan_id}` no existe en el catálogo.\n"
                f"Planes válidos disponibles: {validos}.",
            )
        ]

    msg = formatear_cotizacion_telegram(cot, catalogo.estado, catalogo.version)
    return [Outgoing(user.telegram_id, msg)]


def catalogo_activar_command(
    conn: sqlite3.Connection,
    user: User,
    text: str,
    now: datetime,
    repo: RepositorioCatalogo | None = None,
) -> list[Outgoing]:
    """Comando exclusivo del CTO para marcar una versión como VIGENTE (R3)."""
    if user.role != Role.CTO:
        return [
            Outgoing(
                user.telegram_id,
                "⛔ Permiso denegado: Solo el CTO está autorizado para activar versiones.",
            )
        ]

    r = repo or RepositorioCatalogo()
    partes = text.strip().split()
    if len(partes) < 2:
        return [
            Outgoing(
                user.telegram_id,
                "⚠️ Uso: `/catalogo_activar <version>` (ejemplo: `/catalogo_activar 0.1.0`).",
            )
        ]

    version = partes[1].strip()
    try:
        r.marcar_vigente(version)
    except VersionCatalogoNoEncontradaError:
        return [
            Outgoing(
                user.telegram_id,
                f"❌ No existe el archivo de versión `{version}.yaml` en el catálogo de precios.",
            )
        ]
    except Exception as err:
        return [
            Outgoing(
                user.telegram_id,
                f"❌ Error al activar la versión `{version}`: {err}",
            )
        ]

    return [
        Outgoing(
            user.telegram_id,
            f"✅ *Versión `{version}` activada con éxito.*\n"
            f"El archivo `VIGENTE` ahora apunta a `{version}` y rige para todas las cotizaciones.",
        )
    ]


def catalogo_actualizar_command(
    conn: sqlite3.Connection,
    user: User,
    text: str,
    now: datetime,
    repo: RepositorioCatalogo | None = None,
) -> list[Outgoing]:
    """Comando del CTO para crear una nueva versión semver inmutable de catálogo (R1, R2)."""
    if user.role != Role.CTO:
        return [
            Outgoing(
                user.telegram_id,
                "⛔ Permiso denegado: Solo el CTO puede actualizar o crear versiones de catálogo.",
            )
        ]

    r = repo or RepositorioCatalogo()
    partes = text.strip().split()
    # /catalogo_actualizar <version_nueva> <plan_id> <nuevo_precio>
    if len(partes) < 4:
        return [
            Outgoing(
                user.telegram_id,
                "⚠️ Uso: `/catalogo_actualizar <nueva_version> <plan_id> <nuevo_precio_cop>`\n"
                "Ejemplo: `/catalogo_actualizar 0.2.0 estandar 3500000`",
            )
        ]

    v_nueva = partes[1].strip()
    plan_id = partes[2].strip().lower()
    try:
        nuevo_precio = int(partes[3].replace(".", "").replace(",", ""))
        if nuevo_precio <= 0:
            raise ValueError()
    except ValueError:
        return [
            Outgoing(
                user.telegram_id,
                "⚠️ El precio debe ser un número entero positivo en pesos colombianos (COP).",
            )
        ]

    try:
        base, _ = _obtener_catalogo_activo(r)
    except Exception:
        # Fallback a 0.1.0
        base = r.cargar_version("0.1.0")

    datos: dict[str, Any] = base.model_dump()
    datos["version"] = v_nueva
    datos["estado"] = "borrador"

    encontrado = False
    for p in datos.get("planes", []):
        if p["id"] == plan_id:
            p["precio_propuesta"] = nuevo_precio
            encontrado = True
            break

    if not encontrado:
        validos = ", ".join(f"`{p.id}`" for p in base.planes)
        return [
            Outgoing(
                user.telegram_id,
                f"❌ El plan `{plan_id}` no existe. Planes disponibles: {validos}.",
            )
        ]

    nuevo_catalogo = CatalogoPrecios.model_validate(datos)
    r.guardar_version(nuevo_catalogo)

    return [
        Outgoing(
            user.telegram_id,
            f"✅ *Nueva versión semver `{v_nueva}` creada como borrador inmutable.*\n"
            f"Plan `{plan_id}` actualizado a {_formatear_pesos(nuevo_precio)}.\n"
            f"Para fijarla como oficial, usa: `/catalogo_activar {v_nueva}`.",
        )
    ]


def catalogo_verificar_command(
    conn: sqlite3.Connection,
    user: User,
    text: str,
    now: datetime,
    repo: RepositorioCatalogo | None = None,
) -> list[Outgoing]:
    """Comando exclusivo del CTO para auditar el catálogo contra el modelo financiero (R6)."""
    if user.role != Role.CTO:
        return [
            Outgoing(
                user.telegram_id,
                "⛔ Permiso denegado: Solo el CTO puede auditar el catálogo de precios.",
            )
        ]

    r = repo or RepositorioCatalogo()
    partes = text.strip().split()
    version = partes[1].strip() if len(partes) >= 2 else ""

    try:
        if version:
            cat = r.cargar_version(version)
        else:
            cat, _ = _obtener_catalogo_activo(r)
    except Exception as err:
        return [
            Outgoing(
                user.telegram_id,
                f"❌ Error al cargar la versión a verificar: {err}",
            )
        ]

    archivo_cat = r.directorio / f"{cat.version}.yaml"
    res = verificar_catalogo(archivo_cat)

    simb_sha = "✅" if res.sha256_coincide else "❌"
    simb_val = "✅" if res.valores_coinciden else "❌"
    simb_adv = "✅" if res.advertencias_validas else "❌"

    lineas: list[str] = [
        f"🔍 *Resultado de Verificación — Catálogo v{cat.version}*",
        f"• Estado: `{cat.estado}`",
        f"• Hash SHA-256 de origen: {simb_sha}",
        f"• Concordancia de precios/costos: {simb_val}",
        f"• Advertencias financieras R13: {simb_adv}",
    ]

    if res.discrepancias:
        lineas.append("\n⚠️ *Discrepancias detectadas:*")
        for d in res.discrepancias:
            lineas.append(f"  - {d}")
    else:
        lineas.append("\n✅ *Catálogo 100 % conforme con el modelo financiero de Santiago Jaimes.*")

    return [Outgoing(user.telegram_id, "\n".join(lineas))]


def register_catalogo_commands(
    bot: CrmBot,
    repo: RepositorioCatalogo | None = None,
) -> None:
    """Registra los comandos de catálogo y cotización en el bot del CRM."""
    r = repo or RepositorioCatalogo()

    bot.register_command("catalogo", lambda c, u, t, n: catalogo_command(c, u, t, n, repo=r))
    bot.register_command("cotizar", lambda c, u, t, n: cotizar_command(c, u, t, n, repo=r))
    bot.register_command(
        "catalogo_activar", lambda c, u, t, n: catalogo_activar_command(c, u, t, n, repo=r)
    )
    bot.register_command(
        "catalogo_actualizar",
        lambda c, u, t, n: catalogo_actualizar_command(c, u, t, n, repo=r),
    )
    bot.register_command(
        "catalogo_verificar",
        lambda c, u, t, n: catalogo_verificar_command(c, u, t, n, repo=r),
    )
