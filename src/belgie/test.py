"""Test utility re-exports for belgie consumers."""

_TEST_IMPORT_ERROR = "belgie.test requires the 'test' extra. Install with: uv add belgie[test]"

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
