from typing import Annotated

from fastapi import Depends
from neo4j import AsyncSession

from app.db.connection import get_db

DBDep = Annotated[AsyncSession, Depends(get_db)]
