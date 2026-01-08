#!/usr/bin/env python3
"""
RT-Audit: Real-Time Taskset Auditor
Workload Generator for SCHED_DEADLINE Testing

This script generates synthetic real-time workloads using the UUniFast algorithm
to create realistic SCHED_DEADLINE tasksets for rt-app testing.
"""

import json
import argparse
import math
import os

def generate_json(taskset, num_cpus, system_overhead=0.02, lock_pages=True, ftrace="none", event_type="runtime", verbose=False):
    """
    Convert a taskset into rt-app's JSON format.

    Args:
        taskset (str): A textual description of the taskset as "c p d" lines.
        num_cpus (int): The number of CPUs in the system.
        system_overhead (float): System overhead as fraction (0.0-1.0). Default: 0.02.
        lock_pages (bool): Lock memory pages in RAM. Default: True.
        ftrace (str): Ftrace logging categories. Default: "none".
        event_type (str): Type of workload event: "run" or "runtime". Default: "runtime".
        verbose (bool): Enable verbose output for debugging.

    Returns:
        str: A JSON formatted string representing the rt-app taskset.
    """
    # Define the global configuration for the rt-app workload
    config = {
        "global": {
            "duration": 30,  # Run the simulation for 30 seconds
            "default_policy": "SCHED_DEADLINE",
            "log_basename": "taskset_log",
            "lock_pages": lock_pages,  # Lock memory pages in RAM to prevent RT thread stalling
            "ftrace": ftrace           # Enable ftrace logging: "none", "main", "task", "run", "loop", "stats" or comma-separated list
        },
        "tasks": {}
    }

    # Create the list of CPU affinities for global scheduling
    cpu_affinity = list(range(num_cpus))

    i = 0
    # Generate parameters for each task
    for line in taskset.strip().split('\n'):
        task_name = f"task_{i}"
        i += 1
        task = tuple(map(float, line.split()))

        period_us = task[1] * 1.0
        dl_runtime_us = task[0] * 1.0

        # Apply system overhead to get the actual runtime for the workload events
        # The workload events should be smaller than dl_runtime to account for system overhead
        actual_runtime_us = math.floor(dl_runtime_us * (1.0 - system_overhead))

        # Enforce a minimum runtime. This is a pragmatic trade-off.
        # Rationale:
        # 1. Validity: Prevents generating tasks with a runtime of 0, which is invalid for rt-app.
        # 2. Realism: Tasks with extremely short runtimes (e.g., 1-2µs) are unrealistic,
        #    as scheduler overhead can be greater than the task's execution time.
        # 3. Impact: This only affects tasks with very low utilization and/or short periods.
        #    While it slightly increases the task's actual utilization compared to the
        #    value from UUniFast, the impact on the total taskset utilization is negligible
        #    and ensures a more practical and valid taskset.
        if actual_runtime_us < 10:
            actual_runtime_us = 10
            if verbose:
                print(f"  {task_name}: Adjusted actual runtime from {math.floor(dl_runtime_us * (1.0 - system_overhead))} to {actual_runtime_us} µs (min runtime enforced)")

        if verbose:
            print(f"  {task_name}: period={period_us} µs, dl_runtime={dl_runtime_us} µs, workload_event={actual_runtime_us} µs (overhead: {system_overhead:.1%})")

        # Define the task structure for the JSON output
        task_config = {
            "policy": "SCHED_DEADLINE",
            "dl-runtime": dl_runtime_us,
            "dl-period": period_us,
            "dl-deadline": period_us, # Implicit deadline
            "cpus": cpu_affinity,
            "phases": {
                # A single, infinitely looping phase to represent a periodic task
                f"phase_{i}": {
                    "loop": -1 # Loop indefinitely
                }
            }
        }

        # Add workload events based on the specified event type
        if event_type == "run":
            # Use "run" event: workload-based execution (varies with CPU frequency)
            # The run event executes for a fixed number of loops based on calibration
            task_config["phases"][f"phase_{i}"]["run"] = actual_runtime_us
        elif event_type == "runtime":
            # Use "runtime" event: time-based execution (consistent regardless of CPU frequency)
            # This is the current default behavior
            task_config["phases"][f"phase_{i}"]["runtime"] = actual_runtime_us
        else:
            # Default to runtime if invalid event_type specified
            task_config["phases"][f"phase_{i}"]["runtime"] = actual_runtime_us

        # Add timer event AFTER workload events (rt-app requirement)
        task_config["phases"][f"phase_{i}"]["timer"] = {"ref": "unique", "period": period_us, "mode": "absolute"}

        config["tasks"][task_name] = task_config

    if verbose:
        print(f"Generated tasks for {num_cpus} CPUs using {event_type} events")

    # Return the configuration as a formatted JSON string
    return json.dumps(config, indent=4)

def main():
    """
    Main function to parse command-line arguments and run the generator.
    """
    parser = argparse.ArgumentParser(
        description="Generate a random taskset for rt-app in JSON format.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Arguments for taskset generation
    parser.add_argument("-c", "--cpus", type=int, help="Number of CPUs.")

    # Arguments for file I/O
    parser.add_argument("-o", "--output", type=str, help="Output JSON file name.")
    parser.add_argument("--taskset", type=str, help="Path to a text file describing the taskset.")

    # System configuration
    parser.add_argument("--system-overhead", type=float, default=0.02, help="System overhead as fraction (0.0-1.0). Default: 0.02 (2%%).")

    # rt-app global configuration
    parser.add_argument("--lock-pages", action="store_true", default=True, help="Lock memory pages in RAM (default: True).")
    parser.add_argument("--no-lock-pages", dest="lock_pages", action="store_false", help="Disable memory page locking.")
    parser.add_argument("--ftrace", type=str, default="none", help="Enable ftrace logging: 'none', 'main', 'task', 'run', 'loop', 'stats' or comma-separated list (default: 'none').")

    # Event type for workload events
    parser.add_argument("--event-type", type=str, default="runtime", choices=["run", "runtime"], help="Type of workload event: 'run' or 'runtime' (default: 'runtime').")

    # Debugging options
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output for debugging.")

    args = parser.parse_args()

    # --- Configuration Loading ---
    # Start with an empty config dictionary
    config_params = {}

    # Store verbose flag for later use
    verbose = args.verbose

    # Load from config file first, if provided
    if args.taskset:
        if os.path.exists(args.taskset):
            with open(args.taskset, 'r') as f:
                taskset = f.read()
            if verbose:
                print(f"Loaded configuration from '{args.taskset}': {taskset}")
        else:
            print(f"Error: Configuration file not found at '{args.taskset}'")
            return

    # Override with command-line arguments.
    # An argument is considered provided if it's not None.
    cli_args = {
        'cpus': args.cpus,
        'output': args.output,
        'ftrace': args.ftrace
    }

    # Handle system_overhead separately since it has a default value
    if args.system_overhead != 0.02:  # User explicitly set a different value
        cli_args['system_overhead'] = args.system_overhead

    # Handle lock_pages separately since it has a default value
    if args.lock_pages != True:  # User explicitly set a different value
        cli_args['lock_pages'] = args.lock_pages

    # Handle event_type separately since it has a default value
    if args.event_type != "runtime":  # User explicitly set a different value
        cli_args['event_type'] = args.event_type

    # Filter out None values and update the parameters
    for key, value in cli_args.items():
        if value is not None:
            config_params[key] = value
            if verbose:
                print(f"Override: {key} = {value}")

    # --- Set Defaults and Validate ---
    # Set default values for any parameter that is still missing
    defaults = {
        'output': 'taskset.json',
        'system_overhead': 0.02,
        'lock_pages': True,
        'ftrace': 'none',
        'event_type': 'runtime'
    }
    for key, value in defaults.items():
        if key not in config_params:
            config_params[key] = value
            if verbose:
                print(f"Default: {key} = {value}")

    # Required parameters must be present now
    required_params = ['cpus']
    for param in required_params:
        if param not in config_params:
            print(f"Error: Missing required parameter '{param}'. Provide it via command line or config file.")
            return

    if verbose:
        print(f"\nGenerating taskset with parameters:")
        print(f"  CPUs: {config_params['cpus']}")
        print(f"  System overhead: {config_params['system_overhead']:.1%}")
        print(f"  rt-app options:")
        print(f"    Lock pages: {config_params['lock_pages']}")
        print(f"    Ftrace: {config_params['ftrace']}")
        print(f"    Event type: {config_params['event_type']}")
        print()

    # --- Generate Taskset ---
    taskset_json = generate_json(
        taskset,
        num_cpus=config_params['cpus'],
        system_overhead=config_params['system_overhead'],
        lock_pages=config_params['lock_pages'],
        ftrace=config_params['ftrace'],
        event_type=config_params['event_type'],
        verbose=verbose
    )

    # Check if generation failed
    if taskset_json is None:
        print("Taskset generation failed. Exiting.")
        return

    # Write the JSON to the specified output file
    output_file = config_params['output']
    with open(output_file, 'w') as f:
        f.write(taskset_json)

    if verbose:
        print(f"Generated taskset JSON:")
        print(taskset_json)
        print()

    print(f"Successfully generated taskset and saved to '{output_file}'")
    print(f"To run, use: rt-app {output_file}")

if __name__ == "__main__":
    main()
