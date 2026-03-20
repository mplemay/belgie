import asyncio

import dns.exception
import dns.resolver


async def lookup_txt_records(record_name: str) -> list[str]:
    def _lookup() -> list[str]:
        answers = dns.resolver.resolve(record_name, "TXT")
        records: list[str] = []
        for answer in answers:
            parts = ["".join(chunk.decode() for chunk in answer.strings)]
            records.extend(part for part in parts if part)
        return records

    try:
        return await asyncio.to_thread(_lookup)
    except (dns.exception.DNSException, OSError):
        return []
