import os
import sys
import subprocess
import time
from typing import List, Dict

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Groups of tests
TEST_GROUPS = {
    "Smoke": [
        "check_template.py",
        "test_jinja.py"
    ],
    "Core": [
        "test_api_map_data.py",
        "test_db_integration.py",
        "test_parser_lbc.py"
    ],
    "Network": [
        "test_tls.py"
    ],
    "External APIs": [
        "test_geo.py",
        "test_georisques.py"
    ],
    "Scrapers (Heavy)": [
        "test_lbc.py",
        "test_logicimmo.py",
        "test_uc.py"
    ]
}

def run_script(script_path: str, timeout: int = 60) -> bool:
    """Runs a python script and returns True if it succeeded (exit code 0)."""
    print(f"Running {script_path}...", end=" ", flush=True)
    
    # Set up environment with PYTHONPATH
    env = os.environ.copy()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

    try:
        start_time = time.time()
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        duration = time.time() - start_time
        
        if result.returncode == 0:
            print(f"{GREEN}PASSED{RESET} ({duration:.2f}s)")
            return True
        else:
            print(f"{RED}FAILED{RESET} ({duration:.2f}s)")
            print(f"--- STDOUT ---\n{result.stdout}")
            print(f"--- STDERR ---\n{result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"{RED}TIMEOUT{RESET}")
        return False
    except Exception as e:
        print(f"{RED}ERROR{RESET}: {e}")
        return False

def main():
    ci_mode = "--ci" in sys.argv
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"{BOLD}Immo-Boussole Test Runner{RESET}")
    if ci_mode:
        print(f"{YELLOW}Running in CI mode (skipping heavy tests){RESET}\n")
    
    results: Dict[str, List[bool]] = {}
    
    for group, scripts in TEST_GROUPS.items():
        if ci_mode and group in ["Scrapers (Heavy)", "External APIs"]:
            print(f"Skipping group: {group}")
            continue
            
        print(f"\n{BOLD}[Group: {group}]{RESET}")
        group_results = []
        for script in scripts:
            script_full_path = os.path.join(tests_dir, script)
            if not os.path.exists(script_full_path):
                print(f"{YELLOW}Warning: {script} not found, skipping.{RESET}")
                continue
            
            success = run_script(script_full_path)
            group_results.append(success)
        results[group] = group_results

    # Summary
    print(f"\n{BOLD}--- Test Summary ---{RESET}")
    total_passed = 0
    total_failed = 0
    
    for group, group_res in results.items():
        passed = sum(1 for r in group_res if r)
        failed = len(group_res) - passed
        total_passed += passed
        total_failed += failed
        status = f"{GREEN}OK{RESET}" if failed == 0 else f"{RED}{failed} FAILED{RESET}"
        print(f"{group:20}: {status} ({passed}/{len(group_res)})")
    
    print(f"\n{BOLD}Total: {total_passed} passed, {total_failed} failed.{RESET}")
    
    if total_failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
