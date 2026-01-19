#!/usr/bin/env python3
"""
RT-Audit: Real-Time Taskset Auditor
Workload Generator for SCHED_DEADLINE Testing

This script generates synthetic real-time workloads using the UUniFast algorithm
to create realistic SCHED_DEADLINE tasksets for rt-app testing.
"""

import json
import random
import argparse
import math
import time
import sys
import os

def uunifast(n, u_total):
    """
    The UUniFast algorithm for generating task utilizations.
    This algorithm generates a set of 'n' utilizations that sum to 'u_total'.

    Args:
        n (int): The number of tasks.
        u_total (float): The total utilization to be distributed.

    Returns:
        list: A list of 'n' floating-point utilization values.
    """
    utilizations = []
    sum_u = u_total
    for i in range(1, n):
        # Generate a random value and scale it to the remaining utilization
        next_sum_u = sum_u * random.random() ** (1.0 / (n - i))
        utilizations.append(sum_u - next_sum_u)
        sum_u = next_sum_u
    utilizations.append(sum_u)
    return utilizations

def generate_taskset(num_cpus, num_tasks, period_min_ms, period_max_ms, period_gran_ms, max_task_util, total_utilization, system_overhead=0.02, lock_pages=True, ftrace="none", event_type="runtime", verbose=False):
    """
    Generates a random taskset in rt-app's JSON format.

    Args:
        num_cpus (int): The number of CPUs in the system.
        num_tasks (int): The number of tasks to generate.
        period_min_ms (int): The minimum task period in milliseconds.
        period_max_ms (int): The maximum task period in milliseconds.
        period_gran_ms (int): The period granularity in milliseconds.
        max_task_util (float): The maximum utilization for any single task.
        total_utilization (float): The target total utilization for the taskset.
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

    # Check if the constraint is mathematically possible
    min_required_util = total_utilization / num_tasks
    if min_required_util > max_task_util:
        print(f"Error: Impossible constraint - {num_tasks} tasks with total utilization {total_utilization:.2f}")
        print(f"  Each task must have utilization >= {min_required_util:.3f}, but max_task_util = {max_task_util:.3f}")
        print(f"  Solutions:")
        print(f"    1. Increase max_task_util to at least {min_required_util:.3f}")
        print(f"    2. Decrease the taskset utilization to at most {max_task_util * num_tasks:.2f}")
        print(f"    3. Increase number of tasks")
        return None

    # Generate task utilizations until they meet the max_task_util constraint
    max_attempts = 1000  # Prevent infinite loops
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        task_utils = uunifast(num_tasks, total_utilization)
        if all(u <= max_task_util for u in task_utils):
            if verbose:
                print(f"Generated valid utilizations after {attempts} attempt(s): {[f'{u:.3f}' for u in task_utils]}")
            break
    
    if attempts >= max_attempts:
        print(f"Error: Failed to generate valid utilizations after {max_attempts} attempts")
        print(f"  Consider adjusting parameters:")
        print(f"    - Increase max_task_util (currently {max_task_util:.3f})")
        print(f"    - Decrease the taskset utilization (currently {total_utilization:.3f})")
        print(f"    - Increase number of tasks (currently {num_tasks})")
        return None

    # Create the list of CPU affinities for global scheduling
    cpu_affinity = list(range(num_cpus))

    # Generate parameters for each task
    for i in range(num_tasks):
        task_name = f"task_{i}"
        
        # Get the pre-calculated utilization for this task
        utilization = task_utils[i]
        
        # Randomly select a period within the specified range (in microseconds)
        period_us = random.randint(period_min_ms, period_max_ms) * 1000
        
        # Calculate the deadline runtime (dl_runtime) based on utilization and period
        # This represents the maximum time the task can execute within its deadline
        dl_runtime_us = math.floor(utilization * period_us)

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
            print(f"  {task_name}: util={utilization:.3f}, period={period_us} µs, dl_runtime={dl_runtime_us} µs, workload_event={actual_runtime_us} µs (overhead: {system_overhead:.1%})")
            
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
        print(f"Generated {num_tasks} tasks for {num_cpus} CPUs using {event_type} events")
    
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
    parser.add_argument("-n", "--tasks", type=int, help="Number of tasks to generate.")
    parser.add_argument("-p", "--period-min", type=int, help="Minimum task period in milliseconds.")
    parser.add_argument("-P", "--period-max", type=int, help="Maximum task period in milliseconds.")
    parser.add_argument("-g", "--period-gran", type=int, help="Period granularity.")
    parser.add_argument("-d", "--period-distribution", type=str, help="Period distrubution ('unif' or 'logunif').")
    parser.add_argument("-S", "--seed", type=int, help="Seed for the pseudo-random numbers generator.")
    parser.add_argument("-u", "--taskset-utilization", type=float, help="Target total utilization for the taskset. Defaults to 70%% of system capacity.")
    parser.add_argument("--max-util", type=float, help="Maximum utilization for a single task (0.0 to 1.0).")
    
    # Arguments for file I/O
    parser.add_argument("-o", "--output", type=str, help="Output JSON file name.")
    parser.add_argument("--config", type=str, help="Path to a JSON configuration file with generator parameters.")
    
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
    if args.config:
        if os.path.exists(args.config):
            with open(args.config, 'r') as f:
                config_params = json.load(f)
            if verbose:
                print(f"Loaded configuration from '{args.config}': {config_params}")
        else:
            print(f"Error: Configuration file not found at '{args.config}'")
            return

    # Override with command-line arguments.
    # An argument is considered provided if it's not None.
    cli_args = {
        'cpus': args.cpus,
        'tasks': args.tasks,
        'period_min': args.period_min,
        'period_max': args.period_max,
        'period_gran': args.period_gran,
        'period_distribution': args.period_distribution,
        'seed': args.seed,
        'max_util': args.max_util,
        'taskset_utilization': args.taskset_utilization,
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
        'period_min': 10,
        'period_max': 100,
        'period_gran': 1,
        'period_distribution': "unif",
        'seed': time.time(),
        'max_util': 0.8,
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

    if config_params['period_distribution'] != "unif":
        print(f"Distribution {config_params['period_distribution']} is not supported (yet)")
        sys.exit(-1)

    if config_params['period_gran'] != 1:
        print(f"Period granularity {config_params['period_gran']} is not supported (yet)")
        sys.exit(-1)

    # Required parameters must be present now
    required_params = ['cpus', 'tasks', 'taskset_utilization']
    for param in required_params:
        if param not in config_params:
            print(f"Error: Missing required parameter '{param}'. Provide it via command line or config file.")
            return
            
    if verbose:
        print(f"\nGenerating taskset with parameters:")
        print(f"  CPUs: {config_params['cpus']}")
        print(f"  Tasks: {config_params['tasks']}")
        print(f"  Period range: {config_params['period_min']}-{config_params['period_max']} ms")
        print(f"  Max task utilization: {config_params['max_util']}")
        print(f"  Total utilization: {config_params['taskset_utilization']}")
        print(f"  System overhead: {config_params['system_overhead']:.1%}")
        print(f"  rt-app options:")
        print(f"    Lock pages: {config_params['lock_pages']}")
        print(f"    Ftrace: {config_params['ftrace']}")
        print(f"    Event type: {config_params['event_type']}")
        print()

    # Warn about potential constraint issues
    if config_params['tasks'] < config_params['cpus'] // 2:
        print(f"Warning: Few tasks ({config_params['tasks']}) compared to CPUs ({config_params['cpus']})")
        print(f"  This may cause constraint violations if taskset_utilization is too high")
        print(f"  Consider increasing tasks or decreasing the taskset utilization")
        print()

    random.seed(config_params['seed'])
    # --- Generate Taskset ---
    taskset_json = generate_taskset(
        num_cpus=config_params['cpus'],
        num_tasks=config_params['tasks'],
        period_min_ms=config_params['period_min'],
        period_max_ms=config_params['period_max'],
        period_gran_ms=config_params['period_gran'],
        max_task_util=config_params['max_util'],
        total_utilization=config_params['taskset_utilization'],
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
