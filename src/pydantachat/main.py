from dotenv import load_dotenv
from pydantic_ai import Agent

from pydantachat.telemetry import setup_telemetry

load_dotenv()


def main() -> None:
    setup_telemetry()

    agent = Agent("deepseek:deepseek-flash", system_prompt="you are a superhuman agi")
    resp = agent.run_sync("what is the future of mankind")
    print(resp.output)


if __name__ == "__main__":
    main()
