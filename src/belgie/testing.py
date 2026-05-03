"""Test utility re-exports for belgie consumers."""

_TEST_IMPORT_ERROR = "belgie.testing requires the 'testing' extra. Install with: uv add belgie[testing]"

try:
    from belgie_testing import (
        IndividualData,
        LoginResult,
        OrganizationData,
        OrganizationTestUtils,
        TestCookie,
        TestUtils,
        TestUtilsPlugin,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_TEST_IMPORT_ERROR) from exc

__all__ = [
    "IndividualData",
    "LoginResult",
    "OrganizationData",
    "OrganizationTestUtils",
    "TestCookie",
    "TestUtils",
    "TestUtilsPlugin",
]
