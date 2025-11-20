from enum import StrEnum


class Scope(StrEnum):
    """Example application scopes.

    Users should copy this file to their application and customize
    the scope definitions to match their business logic.

    StrEnum members are strings, so they work directly with FastAPI
    Security and can be compared/checked against string lists.
    """

    # Resource permissions
    RESOURCE_READ = "resource:read"
    RESOURCE_WRITE = "resource:write"
    RESOURCE_DELETE = "resource:delete"

    # User management
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"

    # Admin
    ADMIN = "admin"
