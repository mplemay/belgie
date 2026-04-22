import dns.exception
import dns.resolver
from asyncer import asyncify


async def lookup_txt_records(record_name: str) -> list[str]:
    def _lookup() -> list[str]:
        answers = dns.resolver.resolve(record_name, "TXT")
        records: list[str] = []
        for answer in answers:
            parts = ["".join(chunk.decode() for chunk in answer.strings)]
            records.extend(part for part in parts if part)
        return records

    try:
        return await asyncify(_lookup)()
    except (dns.exception.DNSException, OSError):
        return []
