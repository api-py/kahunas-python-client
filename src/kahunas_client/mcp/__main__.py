"""Entry point for running the MCP server: python -m kahunas_client.mcp"""

from .server import create_server


def main() -> None:
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
