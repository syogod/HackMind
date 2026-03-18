"""
Shared application state passed between UI components.

Holds the open database connection and currently loaded project.
Panels read from this and call engine functions to mutate the DB,
then emit signals to trigger tree refreshes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hackmind.db.database import Database
from hackmind.models.types import Project


@dataclass
class AppState:
    db: Database
    project: Optional[Project] = None

    @property
    def project_open(self) -> bool:
        return self.project is not None
