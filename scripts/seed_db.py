"""Crea la base SQLite sintética de nómina (empleados ficticios y saldos de vacaciones)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hrrag.config import settings  # noqa: E402

SCHEMA = """
DROP TABLE IF EXISTS vacation_requests;
DROP TABLE IF EXISTS vacation_balance;
DROP TABLE IF EXISTS employees;
CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    puesto TEXT NOT NULL,
    area TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('empleado', 'jefe', 'rrhh')),
    fecha_ingreso TEXT NOT NULL,
    salario_base REAL NOT NULL CHECK (salario_base > 0),
    jefe_id TEXT
);
CREATE TABLE vacation_balance (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    periodo TEXT NOT NULL,
    dias_asignados INTEGER NOT NULL,
    dias_gozados INTEGER NOT NULL,
    PRIMARY KEY (employee_id, periodo)
);
CREATE TABLE vacation_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    fecha_inicio TEXT NOT NULL,
    dias INTEGER NOT NULL,
    estado TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
"""

EMPLOYEES = [
    ("EMP-001", "Ana López (ficticio)", "Analista de Compras", "Compras", "empleado", "2019-03-01", 9500.0, "EMP-002"),
    ("EMP-002", "Carlos Méndez (ficticio)", "Coordinador de Compras", "Compras", "jefe", "2015-06-15", 15000.0, None),
    ("EMP-003", "María Juárez (ficticio)", "Generalista de RRHH", "Recursos Humanos", "rrhh", "2018-01-10", 11000.0, None),
    ("EMP-004", "Luis Pérez (ficticio)", "Auxiliar de Bodega", "Operaciones", "empleado", "2025-08-01", 4800.0, "EMP-002"),
    ("EMP-005", "Sofía Ramírez (ficticio)", "Analista Contable", "Finanzas", "empleado", "2023-02-20", 8200.0, None),
]

BALANCES = [
    ("EMP-001", "2024-2025", 15, 15), ("EMP-001", "2025-2026", 16, 4),
    ("EMP-002", "2025-2026", 17, 10),
    ("EMP-003", "2025-2026", 16, 6),
    ("EMP-005", "2025-2026", 15, 15),
]


def seed(db_path: Path = settings.db_path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)", EMPLOYEES)
    con.executemany("INSERT INTO vacation_balance VALUES (?,?,?,?)", BALANCES)
    con.commit()
    con.close()


if __name__ == "__main__":
    seed()
    print(f"Base creada en {settings.db_path}")
