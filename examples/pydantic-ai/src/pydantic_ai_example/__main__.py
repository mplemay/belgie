from pydantic_ai import Agent

from belgie.capabilities.pydantic_ai import Belgie

agent = Agent(
    "openai:gpt-5",
    instructions=(
        "You can execute JavaScript or TypeScript in a Deno sandbox with the run_code tool. "
        "Use it when fetching data or transforming values is easier in JS/TS than in Python."
    ),
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
