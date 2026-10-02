"""Declarative base class shared by the models.

Classes
-------
Base
    Base class of every model mapped to a database table.
"""

from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class of every model mapped to a database table.

    Attributes annotated as str map to text columns.
    """

    type_annotation_map = {str: Text}
