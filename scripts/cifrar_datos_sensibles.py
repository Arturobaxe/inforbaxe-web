"""Cifra PIN/patrón existentes. Por defecto simula; usa --aplicar para escribir."""
import argparse

import database as db
import datos_sensibles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true", help="Escribe los valores cifrados en Supabase.")
    args = parser.parse_args()
    if not datos_sensibles.activo():
        raise SystemExit("Define DATA_ENCRYPTION_KEY antes de ejecutar este script.")

    client = db.get_db()
    offset, page_size, pendientes = 0, 500, 0
    while True:
        rows = (client.table("ventas")
                .select("id,equipo_contrasena,equipo_patron")
                .order("id").range(offset, offset + page_size - 1)
                .execute().data or [])
        for row in rows:
            changes = {}
            for field in datos_sensibles.CAMPOS_SENSIBLES_VENTA:
                value = row.get(field)
                if value and not str(value).startswith(datos_sensibles.PREFIX):
                    changes[field] = datos_sensibles.cifrar(value)
            if changes:
                pendientes += 1
                if args.aplicar:
                    client.table("ventas").update(changes).eq("id", row["id"]).execute()
        if len(rows) < page_size:
            break
        offset += page_size
    print(f"Ventas {'cifradas' if args.aplicar else 'pendientes de cifrar (simulación)'}: {pendientes}")


if __name__ == "__main__":
    main()
