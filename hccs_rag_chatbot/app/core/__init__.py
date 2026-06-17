"""Core package.

The canonical database engine / SessionLocal / Base / get_db live in
app.core.database — every model imports `from app.core.database import Base`.
This module previously declared a SECOND, separate Base + engine here, which
created two independent metadata registries (a subtle source of "table not
found" / duplicate-mapper bugs). It is intentionally left empty now; import
database objects from app.core.database.
"""
