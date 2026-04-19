import os
import sys
import subprocess
import time
import json
from typing import List, Dict, Tuple, Optional

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

def run_script(script_path: str, timeout: int = 60) -> Dict:
    """Runs a python script and returns a result dict with status and details."""
    print(f"Running {script_path}...", end=" ", flush=True)
    
    script_name = os.path.basename(script_path)
    
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
            return {
                "script": script_name,
                "status": "passed",
                "duration": round(duration, 2),
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        else:
            print(f"{RED}FAILED{RESET} ({duration:.2f}s)")
            print(f"--- STDOUT ---\n{result.stdout}")
            print(f"--- STDERR ---\n{result.stderr}")
            return {
                "script": script_name,
                "status": "failed",
                "duration": round(duration, 2),
                "stdout": result.stdout,
                "stderr": result.stderr
            }
    except subprocess.TimeoutExpired:
        print(f"{RED}TIMEOUT{RESET}")
        return {
            "script": script_name,
            "status": "timeout",
            "duration": timeout,
            "stdout": "",
            "stderr": f"Test timed out after {timeout}s"
        }
    except Exception as e:
        print(f"{RED}ERROR{RESET}: {e}")
        return {
            "script": script_name,
            "status": "error",
            "duration": 0,
            "stdout": "",
            "stderr": str(e)
        }

def main():
    ci_mode = "--ci" in sys.argv
    report_path = None
    for arg in sys.argv:
        if arg.startswith("--report="):
            report_path = arg.split("=", 1)[1]
    
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"{BOLD}Immo-Boussole Test Runner{RESET}")
    if ci_mode:
        print(f"{YELLOW}Running in CI mode (skipping heavy tests){RESET}\n")
    
    results: Dict[str, List[Dict]] = {}
    
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
            
            result = run_script(script_full_path)
            result["group"] = group
            group_results.append(result)
        results[group] = group_results

    # Summary
    print(f"\n{BOLD}--- Test Summary ---{RESET}")
    total_passed = 0
    total_failed = 0
    
    for group, group_res in results.items():
        passed = sum(1 for r in group_res if r["status"] == "passed")
        failed = len(group_res) - passed
        total_passed += passed
        total_failed += failed
        status = f"{GREEN}OK{RESET}" if failed == 0 else f"{RED}{failed} FAILED{RESET}"
        print(f"{group:20}: {status} ({passed}/{len(group_res)})")
    
    print(f"\n{BOLD}Total: {total_passed} passed, {total_failed} failed.{RESET}")
    
    # Write JSON report for CI issue management
    if report_path:
        all_tests = []
        for group_res in results.values():
            all_tests.extend(group_res)
        
        report = {
            "total_passed": total_passed,
            "total_failed": total_failed,
            "tests": all_tests
        }
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"\nJSON report written to: {report_path}")
    
    if total_failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
