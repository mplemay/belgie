from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

agent = Agent(
    "openai:gpt-5",
    instructions=(
        "You can execute JavaScript, TypeScript, or TSX in a Deno sandbox with the run_typescript tool. "
        "Use it when fetching data or transforming values is easier in JS/TS than in Python."
    ),
    capabilities=[BelgieSandbox(allow_network=True)],
)


def main() -> None:
    result = agent.run_sync(
        "Use run_typescript with a TypeScript belgie.Script module that exports an async run function "
        "to fetch the Hacker News top stories API and summarize the top headline.",
    )
    print(result.output)  # noqa: T201


if __name__ == "__main__":
    main()
