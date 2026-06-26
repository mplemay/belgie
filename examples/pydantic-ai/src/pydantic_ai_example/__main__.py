from pydantic_ai import Agent

from belgie.capabilities.pydantic_ai import Belgie

agent = Agent(
    "openai:gpt-5",
    capabilities=[Belgie()],
)


def main() -> None:
    result = agent.run_sync(
        "Use run_code with a TypeScript belgie.Script module that exports an async run function "
        "to fetch the Hacker News top stories API and summarize the top headline.",
    )
    print(result.output)  # noqa: T201


if __name__ == "__main__":
    main()
