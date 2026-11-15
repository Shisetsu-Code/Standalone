"""Compatibility entry point for the suite general provider relay."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'demo-dashboard'))
from provider_relay import main, make_handler, pump, public_addresses, validate_target, RelayState
if __name__ == '__main__': main()
