from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property

from authlib.oauth2.rfc6749 import JsonPayload, JsonRequest, OAuth2Payload, OAuth2Request
from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

_REDIRECT_STATUS_MIN = 300
_REDIRECT_STATUS_MAX = 400
type JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportRequestData:
    method: str
    uri: str
    headers: tuple[tuple[str, str], ...]
    query_items: tuple[tuple[str, str], ...]
    form_items: tuple[tuple[str, str], ...]
    json_data: dict[str, JSONValue] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportResponse:
    status_code: int
    body: dict[str, JSONValue] | str
    headers: tuple[tuple[str, str], ...]


class HeaderMap(Mapping[str, str]):
    def __init__(self, headers: tuple[tuple[str, str], ...]) -> None:
        self._headers = {key.lower(): value for key, value in headers}

    def __getitem__(self, key: str) -> str:
        return self._headers[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return iter(self._headers)

    def __len__(self) -> int:
        return len(self._headers)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._headers.get(key.lower(), default)


class StarletteOAuth2Payload(OAuth2Payload):
    def __init__(self, request: TransportRequestData) -> None:
        self._request = request

    @cached_property
    def data(self) -> dict[str, str]:
        data = dict(self._request.query_items)
        data.update(self._request.form_items)
        return data

    @cached_property
    def datalist(self) -> defaultdict[str, list[str]]:
        values: defaultdict[str, list[str]] = defaultdict(list)
        for key, value in (*self._request.query_items, *self._request.form_items):
            values[key].append(value)
        return values


class StarletteOAuth2Request(OAuth2Request):
    def __init__(self, request: TransportRequestData) -> None:
        self.method = request.method
        self.uri = request.uri
        self.headers = HeaderMap(request.headers)
        self._body = None
        self.payload = StarletteOAuth2Payload(request)
        self.client = None
        self.auth_method = None
        self.user = None
        self.authorization_code = None
        self.refresh_token = None
        self.credential = None
        self._scope = None
        self._request = request

    @cached_property
    def args(self) -> dict[str, str]:
        return dict(self._request.query_items)

    @cached_property
    def form(self) -> dict[str, str]:
        return dict(self._request.form_items)


class StarletteJsonPayload(JsonPayload):
    def __init__(self, request: TransportRequestData) -> None:
        self._request = request

    @property
    def data(self) -> dict[str, JSONValue]:
        return self._request.json_data or {}


class StarletteJsonRequest(JsonRequest):
    def __init__(self, request: TransportRequestData) -> None:
        super().__init__(request.method, request.uri, HeaderMap(request.headers))
        self.payload = StarletteJsonPayload(request)


async def load_transport_request(request: Request) -> TransportRequestData:
    query_items = tuple((str(key), str(value)) for key, value in request.query_params.multi_items())
    form_items: tuple[tuple[str, str], ...] = ()
    json_data: dict[str, JSONValue] | None = None

    if request.method != "GET":
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                payload = await request.json()
            except ValueError:
                payload = {}
            if isinstance(payload, dict):
                json_data = {str(key): value for key, value in payload.items()}
        else:
            form = await request.form()
            form_items = tuple((str(key), str(value)) for key, value in form.multi_items() if isinstance(value, str))

    return TransportRequestData(
        method=request.method,
        uri=str(request.url),
        headers=tuple((str(key), value) for key, value in request.headers.items()),
        query_items=query_items,
        form_items=form_items,
        json_data=json_data,
    )


def to_fastapi_response(transport_response: TransportResponse) -> Response:
    headers = dict(transport_response.headers)
    location = headers.get("Location")
    if location is not None and _REDIRECT_STATUS_MIN <= transport_response.status_code < _REDIRECT_STATUS_MAX:
        redirect_headers = {key: value for key, value in headers.items() if key.lower() != "location"}
        return RedirectResponse(
            url=location,
            status_code=transport_response.status_code,
            headers=redirect_headers,
        )
    if isinstance(transport_response.body, dict):
        return JSONResponse(
            transport_response.body,
            status_code=transport_response.status_code,
            headers=headers,
        )
    return Response(
        content=transport_response.body,
        status_code=transport_response.status_code,
        headers=headers,
    )
