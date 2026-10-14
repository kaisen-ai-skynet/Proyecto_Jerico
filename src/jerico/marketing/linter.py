"""Validador algorítmico determinista de reglas de marca Kaizen (Spec 008, M2).

Aplica las directrices del Manual de Marca v1.0 y GUIA_MARCA.md:
- Uso estricto de «Kaizen» (rechaza «Kaisen», «AI»).
- Exclusividad de trato sin mezcla («tú» vs. «usted»).
- Invariabilidad del tagline «Da el paso. Nosotros respondemos.».
- Prohibición de palabras vacías («disruptivo», «revolucionario»).
- Reglas de accesibilidad y contraste de tokens de color.
"""

import re

from jerico.schemas.marketing import (
    CanalMarketing,
    LinterResult,
    LinterViolation,
    Trato,
)

TAGLINE_OFICIAL = "Da el paso. Nosotros respondemos."

_PALABRAS_PROHIBIDAS = [
    r"\brevolucionari[oa]s?\b",
    r"\bdisruptiv[oa]s?\b",
    r"\btransformaci[oó]n\s+digital\b",
    r"\bsoluciones?\s+innovadoras?\b",
    r"\bde\s+[uú]ltima\s+generaci[oó]n\b",
    r"\btripulaci[oó]n\b",
    r"\brecupera\s+el\s+tim[oó]n\b",
    r"\bm[aá]gic[oa]s?\b",
    r"\bcaja\s+negra\b",
]

_NOMBRES_PROHIBIDOS = [
    r"\bkaisen\b",
    r"\bkaizen\s*ai\b",
    r"\bkaizen\.ai\b",
    r"\bkaizenai\b",
    r"\bkaisen\s*ai\b",
]

_TOKENS_TU = {
    "tu", "tus", "tuyo", "tuya", "tuyos", "tuyas", "te", "ti", "contigo",
    "quieres", "tienes", "puedes", "haces", "ves", "sabes", "entiendes",
    "escribeme", "escríbeme", "cuentame", "cuéntame", "avisame", "avísame",
    "mira", "busca", "entra",
}

_TOKENS_USTED = {
    "su", "sus", "suyo", "suya", "suyos", "suyas", "le", "les", "usted", "ustedes",
    "estimado", "estimada", "quiere", "tiene", "puede", "hace", "ve", "sabe",
    "entiende", "escribame", "escríbame", "cuenteme", "cuénteme", "aviseme",
    "avíseme", "mire", "busque", "ingrese",
}

# Fondos claros donde oxido_vivo (#CD7041) y oro (#B8862B) tienen contraste < 4.5
_FONDOS_CLAROS_HEX = {"#ffffff", "#f8f4ed", "#eee5d6"}
_TEXTOS_PROHIBIDOS_SOBRE_CLARO = {"#cd7041", "#b8862b"}


class LinterMarcaKaizen:
    """Linter determinista para piezas de contenido y diseño de Kaizen."""

    def validar(
        self,
        copy: str,
        canal: CanalMarketing | str,
        trato: Trato | str | None = None,
    ) -> LinterResult:
        errores: list[LinterViolation] = []
        advertencias: list[LinterViolation] = []

        canal_enum = CanalMarketing(canal) if isinstance(canal, str) else canal
        trato_enum = Trato(trato) if isinstance(trato, str) else trato

        # 1. Validación de Nombres
        nombre_valido = True
        for pat in _NOMBRES_PROHIBIDOS:
            match = re.search(pat, copy, re.IGNORECASE)
            if match:
                nombre_valido = False
                msg = (
                    f"Uso de nombre prohibido detectado: '{match.group(0)}' "
                    "(use exclusivamente 'Kaizen' con Z y sin 'AI')."
                )
                errores.append(LinterViolation(regla="nombre", mensaje=msg))
                break

        # 2. Validación de Palabras Prohibidas
        for pat in _PALABRAS_PROHIBIDAS:
            match = re.search(pat, copy, re.IGNORECASE)
            if match:
                errores.append(
                    LinterViolation(
                        regla="vocabulario_prohibido",
                        mensaje=f"Palabra o frase prohibida detectada: '{match.group(0)}'.",
                    )
                )

        # 3. Validación de Tagline
        tagline_valido = True
        variaciones_tagline = [
            r"\bden\s+el\s+paso\b",
            r"\bdemos\s+el\s+paso\b",
            r"\bdar\s+el\s+paso\b",
            r"\bnosotros\s+respondemos\b",
        ]
        tiene_variacion = any(re.search(pat, copy, re.IGNORECASE) for pat in variaciones_tagline)
        tiene_exacto = TAGLINE_OFICIAL.lower() in copy.lower()

        if tiene_variacion and not tiene_exacto:
            tagline_valido = False
            msg = (
                "El tagline no se conjuga ni se varía. "
                f"Debe ser exactamente: '{TAGLINE_OFICIAL}'."
            )
            errores.append(LinterViolation(regla="tagline_invariable", mensaje=msg))

        # 4. Validación de Trato (Tú vs. Usted) y No Mezcla
        # Para evitar falsos positivos con el tagline invariable, se remueve antes de evaluar.
        texto_sin_tagline = copy.replace(TAGLINE_OFICIAL, "").replace(TAGLINE_OFICIAL.lower(), "")
        palabras = [
            w.strip(".,;:?!¿¡()\"'\n\r").lower() for w in re.split(r"\s+", texto_sin_tagline)
        ]
        palabras_set = set(palabras)

        puntuacion_tu = len(palabras_set.intersection(_TOKENS_TU))
        puntuacion_usted = len(palabras_set.intersection(_TOKENS_USTED))

        trato_detectado: str | None = None
        if puntuacion_tu > 0 and puntuacion_usted == 0:
            trato_detectado = Trato.TU.value
        elif puntuacion_usted > 0 and puntuacion_tu == 0:
            trato_detectado = Trato.USTED.value
        elif puntuacion_tu > 0 and puntuacion_usted > 0:
            trato_detectado = "mezcla"
            msg = (
                "Se detectó mezcla de 'tú' y 'usted' en la misma pieza. "
                "El trato debe ser uniforme."
            )
            errores.append(LinterViolation(regla="mezcla_trato", mensaje=msg))

        # Validar consistencia con el trato declarado
        if trato_enum and trato_detectado and trato_detectado != "mezcla":
            if trato_detectado != trato_enum.value:
                msg = (
                    f"El trato detectado ('{trato_detectado}') difiere del "
                    f"trato esperado ('{trato_enum.value}')."
                )
                advertencias.append(
                    LinterViolation(
                        regla="trato_inconsistente",
                        mensaje=msg,
                        severidad="advertencia",
                    )
                )

        # Validar concordancia de canal
        if canal_enum == CanalMarketing.CORREO and trato_detectado == Trato.TU.value:
            advertencias.append(
                LinterViolation(
                    regla="canal_trato",
                    mensaje="En correos formales o de prospección se recomienda 'usted'.",
                    severidad="advertencia",
                )
            )

        valido = len(errores) == 0

        return LinterResult(
            valido=valido,
            errores=errores,
            advertencias=advertencias,
            nombre_valido=nombre_valido,
            trato_detectado=trato_detectado,
            tagline_valido=tagline_valido,
            tokens_validos=True,
        )

    def validar_contraste(self, color_texto: str, color_fondo: str) -> LinterResult:
        """Valida que la combinación de color cumpla la regla de accesibilidad de la marca."""
        errores: list[LinterViolation] = []
        ctx = color_texto.strip().lower()
        cfondo = color_fondo.strip().lower()

        tokens_validos = True
        if cfondo in _FONDOS_CLAROS_HEX and ctx in _TEXTOS_PROHIBIDOS_SOBRE_CLARO:
            tokens_validos = False
            msg = (
                f"Contraste ilegal: el color de texto '{color_texto}' (Óxido vivo u Oro) "
                f"no cumple WCAG AA sobre el fondo claro '{color_fondo}'. Solo gráficos."
            )
            errores.append(LinterViolation(regla="contraste_tokens", mensaje=msg))

        return LinterResult(
            valido=len(errores) == 0,
            errores=errores,
            tokens_validos=tokens_validos,
        )
