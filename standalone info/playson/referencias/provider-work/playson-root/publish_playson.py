"""Compatibility entry point for the provider-local report command."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"demo-dashboard"))
from playson_reports import publish
if __name__=="__main__":
 d=publish();print({k:d[k]for k in ["completed_games","complete_modes","pending"]})
