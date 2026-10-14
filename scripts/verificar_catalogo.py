#!/usr/bin/env python3
"""Script de verificación del catálogo de precios contra el modelo financiero (Spec 006, C6).

Compara las cifras del archivo YAML del catálogo con el archivo Excel de origen
o con los valores canónicos del modelo de Santiago Jaimes (R6, R13).
"""

import argparse
import sys
from pathlib import Path

from jerico.catalogo.verificador import verificar_catalogo


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verificador del catálogo de precios contra modelo financiero (Spec 006, C6)."
    )
    parser.add_argument(
        "--catalogo",
        type=Path,
        default=Path("catalogo/precios/0.1.0.yaml"),
        help="Ruta al archivo YAML del catálogo (default: catalogo/precios/0.1.0.yaml)",
    )
    parser.add_argument(
        "--excel",
        type=Path,
        default=Path("/home/janty-mr/Documentos/Docs Kaisen.ai/Kaizen_Modelo_Financiero_5A_8.xlsx"),
        help="Ruta al archivo Excel del modelo financiero.",
    )
    parser.add_argument(
        "--solo-hash",
        action="store_true",
        help="Verifica solo SHA-256 del Excel y valida valores contra referencia canónica.",
    )

    args = parser.parse_args()

    excel_p = args.excel if args.excel.exists() else None

    print(f"=== Verificando catálogo: {args.catalogo} ===")
    if excel_p:
        print(f"Fuente Excel detectada: {excel_p}")
    else:
        print("Fuente Excel no encontrada localmente; usando hash y valores de referencia.")

    res = verificar_catalogo(args.catalogo, excel_path=excel_p, solo_hash=args.solo_hash)

    print(f"Versión: {res.detalles.get('version', 'desconocida')}")
    print(f"Estado: {res.detalles.get('estado', 'desconocido')}")
    print(f"SHA-256 coincide: {'✅ SÍ' if res.sha256_coincide else '❌ NO'}")
    print(f"Valores coinciden: {'✅ SÍ' if res.valores_coinciden else '❌ NO'}")
    print(f"Advertencias obligatorias R13: {'✅ SÍ' if res.advertencias_validas else '❌ NO'}")

    if res.discrepancias:
        print("\n❌ Discrepancias encontradas:")
        for disc in res.discrepancias:
            print(f"  - {disc}")
        return 1

    print("\n✅ Catálogo 100 % validado y conforme con el modelo financiero (R6, R13).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
