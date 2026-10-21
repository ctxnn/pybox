"""Absolute-path launcher; usable without changing a client's working directory."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pybox.mcp import serve
if __name__=='__main__':sys.exit(serve())
