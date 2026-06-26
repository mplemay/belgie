from typing import Final

from pydantic_ai import Agent

from belgie.capabilities.pydantic_ai import Belgie

HACKER_NEWS_PROMPT: Final[str] = (
    "Across the top, best, and 'show HN' Hacker News feeds, find the most-discussed "
    "story with at least 100 points. Pull its comment thread, its submitter's profile, "
    "and any web coverage. Summarize what you find in one paragraph."
)


def build_agent(model: str = "openai:gpt-5") -> Agent[None, str]:
    return Agent(
        model,
        capabilities=[Belgie()],
    )


def summarize_hacker_news() -> str:
    agent = build_agent()
    result = agent.run_sync(HACKER_NEWS_PROMPT)
    return str(result.output)


def main() -> None:
    print(summarize_hacker_news())  # noqa: T201


if __name__ == "__main__":
    main()
