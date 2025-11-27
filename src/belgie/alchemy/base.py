from datetime import datetime
from typing import Any, ClassVar, Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

from belgie.alchemy.types import DateTimeUTC

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TYPE_ANNOTATION_MAP: Final[dict[type | Any, object]] = {
    datetime: DateTimeUTC,
}


class Base(MappedAsDataclass, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = TYPE_ANNOTATION_MAP
    __sa_dataclass_kwargs__: ClassVar[dict[str, bool]] = {"kw_only": True, "repr": True, "eq": True}
