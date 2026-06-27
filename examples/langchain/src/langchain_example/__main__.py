from langchain.agents import create_agent

from belgie.capabilities.langchain import BelgieMiddleware

agent = create_agent(
    model="openai:gpt-5",
    tools=[],
    middleware=[BelgieMiddleware()],
    system_prompt=(
        "You can execute JavaScript or TypeScript in a Deno sandbox with the run_code tool. "
        "Use it when fetching data or transforming values is easier in JS/TS than in Python."
    ),
)


def main() -> None:
    result = agent.invoke(
        {
            "messages": [
                (
                    "user",
                    "Use run_code with a TypeScript belgie.Script module that exports an async run function "
                    "to fetch the Hacker News top stories API and summarize the top headline.",
                ),
            ],
        },
    )
    print(result["messages"][-1].content)  # noqa: T201


if __name__ == "__main__":
    main()
