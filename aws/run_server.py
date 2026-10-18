"""AWS MCP server entry point."""
import sys 
import os 

sys.path.insert(0, os.path.join(os.path.dirname(__file__),"src"))

import asyncio
from aws_mcp.server import main


if __name__ == "__main__":
    asyncio.run(main())
